from __future__ import annotations

from collections import deque
from dataclasses import replace
from queue import Empty, Full, Queue
from threading import Lock
from typing import Any

from contracts.frontend import FrontendEvent


class FrontendSubscription:
    def __init__(
        self,
        bus: "BehaviourBus",
        client_id: str,
        event_queue: Queue[FrontendEvent],
    ) -> None:
        self._bus = bus
        self.client_id = client_id
        self._queue = event_queue
        self._closed = False

    def get(self, timeout: float | None = None) -> FrontendEvent | None:
        if self._closed:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._bus.unsubscribe(self.client_id, self._queue)


class BehaviourBus:
    """Thread-safe, replayable event hub for Electron clients.

    The dispatcher and FastAPI run on different threads/event loops, so this
    hub deliberately uses standard library synchronization primitives.
    """

    def __init__(self, history_size: int = 256, subscriber_size: int = 128):
        self._history: deque[FrontendEvent] = deque(maxlen=history_size)
        self._subscribers: dict[str, list[Queue[FrontendEvent]]] = {}
        self._subscriber_size = subscriber_size
        self._lock = Lock()
        self._sequence = 0

    def publish(
        self,
        event: FrontendEvent,
        *,
        target_client_id: str | None = None,
    ) -> FrontendEvent:
        with self._lock:
            self._sequence += 1
            event = replace(
                event,
                seq=self._sequence,
                target_client_id=target_client_id,
            )
            self._history.append(event)
            targets = [
                event_queue
                for client_id, queues in self._subscribers.items()
                if target_client_id is None or client_id == target_client_id
                for event_queue in queues
            ]

        for event_queue in targets:
            self._put_latest(event_queue, event)
        return event

    def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        trace_id: str = "",
        session_id: str = "desktop-local",
        target_client_id: str | None = None,
    ) -> FrontendEvent:
        return self.publish(
            FrontendEvent(
                type=event_type,
                payload=payload or {},
                trace_id=trace_id,
                session_id=session_id,
            ),
            target_client_id=target_client_id,
        )

    def subscribe(
        self,
        client_id: str,
        *,
        after_seq: int = 0,
    ) -> FrontendSubscription:
        event_queue: Queue[FrontendEvent] = Queue(self._subscriber_size)
        with self._lock:
            replay = [
                event
                for event in self._history
                if event.seq > after_seq
                and (
                    event.target_client_id is None
                    or event.target_client_id == client_id
                )
            ]
            self._subscribers.setdefault(client_id, []).append(event_queue)
        for event in replay[-self._subscriber_size :]:
            self._put_latest(event_queue, event)
        return FrontendSubscription(self, client_id, event_queue)

    def unsubscribe(
        self,
        client_id: str,
        event_queue: Queue[FrontendEvent],
    ) -> None:
        with self._lock:
            queues = self._subscribers.get(client_id, [])
            if event_queue in queues:
                queues.remove(event_queue)
            if not queues:
                self._subscribers.pop(client_id, None)

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    @staticmethod
    def _put_latest(
        event_queue: Queue[FrontendEvent],
        event: FrontendEvent,
    ) -> None:
        try:
            event_queue.put_nowait(event)
            return
        except Full:
            pass

        # A desktop client that cannot keep up should see the newest visual
        # state instead of replaying a long-obsolete animation backlog.
        try:
            event_queue.get_nowait()
        except Empty:
            pass
        try:
            event_queue.put_nowait(event)
        except Full:
            pass
