# background_worker/backworker.py
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from threading import Event as ThreadEvent

from contracts.event import Event
from event.event_bus import EventBus
from background_worker.session_handler import SessionWriteHandler

logger = logging.getLogger(__name__)
EventHandler = Callable[[Event], Awaitable[None]]


class BackgroundWorker:
    def __init__(
        self,
        event_bus: EventBus,
        max_retries: int = 3,
    ) -> None:
        self.event_bus = event_bus
        self.max_retries = max_retries
        self.handlers: dict[str, EventHandler] = {
            "session_write": SessionWriteHandler()
        }

    def run_forever(self, stop_event: ThreadEvent) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 收到停止信号后继续排空已有事件。
            while not stop_event.is_set() or not self.event_bus.empty():
                event = self.event_bus.consume(block=True, timeout=0.2)
                if event is None:
                    continue

                try:
                    handler = self.handlers.get(event.event_type)
                    if handler is None:
                        raise ValueError(
                            f"No handler for event: {event.event_type}"
                        )

                    loop.run_until_complete(handler(event))
                except Exception:
                    logger.exception(
                        "Background event failed: %s", event.event_id
                    )
                    self._retry(event, stop_event)
                finally:
                    self.event_bus.task_done()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()

    def _retry(
        self,
        event: Event,
        stop_event: ThreadEvent,
    ) -> None:
        if event.attempts >= self.max_retries:
            logger.error("Event moved to dead letter: %s", event.event_id)
            return

        delay = min(2 ** event.attempts, 10)
        stop_event.wait(delay)

        self.event_bus.publish(
            replace(event, attempts=event.attempts + 1)
        )