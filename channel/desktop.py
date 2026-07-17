from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any
from uuid import uuid4

from behaviour.behaviour_bus import BehaviourBus
from channel.base import BaseChannel
from contracts.frontend import FrontendEvent
from contracts.media import Media
from contracts.message import Message
from message.message_bus import MessageBus
from message.message_post_bus import MessagePost


TOUCH_LABELS = {
    "head": "用户轻轻摸了摸你的头",
    "face": "用户碰了碰你的脸",
    "hair": "用户轻轻拨弄了一下你的头发",
    "body": "用户轻轻碰了碰你",
    "accessory": "用户好奇地碰了碰你的配饰",
}


@dataclass(slots=True)
class _TouchInFlight:
    trace_id: str
    accepted_at: float


class DesktopChannel(BaseChannel):
    name = "desktop"
    channel_id = "desktop"

    def __init__(
        self,
        message_bus: MessageBus,
        frontend_bus: BehaviourBus,
        *,
        touch_cooldown_ms: int = 1200,
        touch_inflight_timeout_s: float = 120.0,
    ) -> None:
        super().__init__(message_bus)
        self.frontend_bus = frontend_bus
        self.touch_cooldown_s = max(0, touch_cooldown_ms) / 1000
        self.touch_inflight_timeout_s = max(1.0, touch_inflight_timeout_s)
        self._touch_lock = Lock()
        self._touch_last_accepted: dict[str, float] = {}
        self._touch_inflight: dict[str, _TouchInFlight] = {}
        self._touch_trace_sessions: dict[str, str] = {}
        self._seen_touch_events: dict[str, float] = {}

    def receive_message(self, message: MessagePost | str) -> None:
        if isinstance(message, str):
            self.frontend_bus.publish_event(
                "agent.delta",
                {"content": message},
            )
            return
        if message.event_type == "agent.done":
            self._finish_touch(message.trace_id)
        payload = {
            "content": message.content,
            "message_id": message.message_id,
            "is_final": message.is_final,
        }
        if message.event_type == "error":
            payload["message"] = message.content
        self.frontend_bus.publish_event(
            message.event_type,
            payload,
            trace_id=message.trace_id,
            session_id=message.session_id or "desktop-local",
        )

    def accept_event(
        self,
        event: FrontendEvent,
        *,
        client_id: str,
    ) -> Message | None:
        payload = event.payload
        user_id = str(payload.get("user_id") or "desktop-user")
        session_id = event.session_id or f"desktop:{client_id}"
        if event.type == "input.touch" and not event.trace_id:
            event.trace_id = str(uuid4())

        if event.type == "input.text":
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("text input cannot be empty")
            message = self.build_message(
                text,
                user_id=user_id,
                session_id=session_id,
                metadata={"client_id": client_id, "source_event_id": event.event_id},
            )
        elif event.type == "input.touch":
            ignored_reason = self._reserve_touch(
                event,
                session_id=session_id,
            )
            if ignored_reason:
                self.frontend_bus.publish_event(
                    "input.ignored",
                    {
                        "source_event_id": event.event_id,
                        "reason": ignored_reason,
                    },
                    trace_id=event.trace_id,
                    session_id=session_id,
                    target_client_id=client_id,
                )
                return None
            region = str(payload.get("region") or "body")
            gesture = str(payload.get("gesture") or "tap")
            text = TOUCH_LABELS.get(region, TOUCH_LABELS["body"])
            message = self.build_message(
                text,
                user_id=user_id,
                session_id=session_id,
                kind="interaction",
                metadata={
                    "client_id": client_id,
                    "source_event_id": event.event_id,
                    "interaction": {**payload, "region": region, "gesture": gesture},
                },
            )
        elif event.type == "input.audio":
            transcript = str(payload.get("transcript") or "").strip()
            audio_path = str(payload.get("path") or "")
            message = Message(
                user_id=user_id,
                channel_id=self.channel_id,
                session_id=session_id,
                kind="audio",
                content=transcript or "[用户发送了一条语音消息]",
                media=[
                    Media(
                        media_id=str(payload.get("audio_id") or ""),
                        path=audio_path or None,
                        type="audio",
                        mime_type=str(payload.get("mime_type") or "audio/webm"),
                        size=int(payload.get("size") or 0),
                        duration_ms=int(payload.get("duration_ms") or 0),
                        transcript=transcript or None,
                    )
                ],
                metadata={"client_id": client_id, "source_event_id": event.event_id},
            )
        else:
            return None

        # Preserve the trace generated by the client when available.
        if event.trace_id:
            message.trace_id = event.trace_id
        self.push_message(message)
        self.frontend_bus.publish_event(
            "input.accepted",
            {"message_id": message.message_id, "source_event_id": event.event_id},
            trace_id=message.trace_id,
            session_id=session_id,
            target_client_id=client_id,
        )
        return message

    def _reserve_touch(
        self,
        event: FrontendEvent,
        *,
        session_id: str,
    ) -> str | None:
        now = monotonic()
        with self._touch_lock:
            self._prune_touch_state(now)
            if event.event_id in self._seen_touch_events:
                return "duplicate"
            self._seen_touch_events[event.event_id] = now

            if session_id in self._touch_inflight:
                return "busy"

            last_accepted = self._touch_last_accepted.get(session_id)
            if (
                last_accepted is not None
                and now - last_accepted < self.touch_cooldown_s
            ):
                return "cooldown"

            self._touch_last_accepted[session_id] = now
            self._touch_inflight[session_id] = _TouchInFlight(
                trace_id=event.trace_id,
                accepted_at=now,
            )
            self._touch_trace_sessions[event.trace_id] = session_id
        return None

    def _finish_touch(self, trace_id: str) -> None:
        if not trace_id:
            return
        with self._touch_lock:
            session_id = self._touch_trace_sessions.pop(trace_id, None)
            if session_id is None:
                return
            inflight = self._touch_inflight.get(session_id)
            if inflight and inflight.trace_id == trace_id:
                self._touch_inflight.pop(session_id, None)

    def _prune_touch_state(self, now: float) -> None:
        duplicate_ttl_s = max(30.0, self.touch_inflight_timeout_s)
        for event_id, seen_at in list(self._seen_touch_events.items()):
            if now - seen_at >= duplicate_ttl_s:
                self._seen_touch_events.pop(event_id, None)

        for session_id, inflight in list(self._touch_inflight.items()):
            if now - inflight.accepted_at < self.touch_inflight_timeout_s:
                continue
            self._touch_inflight.pop(session_id, None)
            self._touch_trace_sessions.pop(inflight.trace_id, None)

        for session_id, last_accepted in list(self._touch_last_accepted.items()):
            if (
                session_id not in self._touch_inflight
                and now - last_accepted >= duplicate_ttl_s
            ):
                self._touch_last_accepted.pop(session_id, None)

    def send_message(self, prompt: str | None = None) -> Message:
        raise RuntimeError("Desktop input is accepted through FastAPI WebSocket")
