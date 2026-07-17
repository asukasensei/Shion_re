import asyncio
from threading import Event
from dataclasses import replace

from agent.main_agent import MainAgent
from contracts.message import Message
from event.event_bus import EventBus
from message.message_bus import MessageBus
from message.message_post_bus import MessagePost, MessagePostBus
from contracts.event import Event


class Dispatcher:
    def __init__(
        self,
        message_bus: MessageBus,
        message_post_bus: MessagePostBus,
        event_bus: EventBus,
        main_agent: MainAgent,
    ) -> None:
        self.message_bus = message_bus
        self.message_post_bus = message_post_bus
        self.event_bus = event_bus
        self.main_agent = main_agent

    def dispatch_once(self, block: bool = True, timeout: float = 0.2) -> bool:
        message = self.message_bus.pop_message(block=block, timeout=timeout)
        if message is None:
            return False

        try:
            asyncio.run(self._dispatch_message(message))
        except Exception as exc:
            self.message_post_bus.push_message(
                MessagePost(
                    channel=message.channel_id,
                    content=f"[agent error] {exc}",
                    trace_id=message.trace_id,
                    session_id=message.session_id or message.trace_id,
                    user_id=message.user_id,
                    event_type="error",
                    is_final=True,
                )
            )
        finally:
            self.message_bus.task_done()

        return True

    async def _dispatch_message(self, message: Message) -> None:
        response_parts: list[str] = []

        try:
            async for post in self.main_agent.run(message):
                self._push_post(message, post)
                response_parts.append(post.content)
        finally:
            self.message_post_bus.push_message(
                MessagePost(
                    channel=message.channel_id,
                    content="",
                    trace_id=message.trace_id,
                    session_id=message.session_id or message.trace_id,
                    user_id=message.user_id,
                    event_type="agent.done",
                    is_final=True,
                )
            )
            event = Event(
                event_type="session_write",
                event_id=f"session-write:{message.message_id}",
                priority="immediate",
                content={
                    "time": message.created_at,
                    "user_id": message.user_id,
                    "session_id": message.session_id or message.trace_id,
                    "channel_id": message.channel_id,
                    "message_id": message.message_id,
                    "trace_id": message.trace_id,
                    "user": message.content,
                    "agent_response": "".join(response_parts),
                },
            )
            self.event_bus.publish(event)

    def run_forever(self, stop_event: Event) -> None:
        while not stop_event.is_set():
            self.dispatch_once(block=True, timeout=0.2)

    def _push_post(self, source: Message, post: MessagePost | str | dict) -> None:
        if isinstance(post, MessagePost):
            self.message_post_bus.push_message(
                replace(
                    post,
                    trace_id=post.trace_id or source.trace_id,
                    session_id=(
                        post.session_id or source.session_id or source.trace_id
                    ),
                    user_id=post.user_id or source.user_id,
                )
            )
            return
        if isinstance(post, str):
            self.message_post_bus.push_message(
                MessagePost(
                    channel=source.channel_id,
                    content=post,
                    trace_id=source.trace_id,
                    session_id=source.session_id or source.trace_id,
                    user_id=source.user_id,
                )
            )
            return
        self.message_post_bus.push_message(
            MessagePost(
                channel=source.channel_id,
                content=str(post),
                trace_id=source.trace_id,
                session_id=source.session_id or source.trace_id,
                user_id=source.user_id,
            )
        )
