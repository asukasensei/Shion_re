
# event/event_bus.py
from queue import Empty, Queue

from contracts.event import Event


class EventBus:
    def __init__(self) -> None:
        self._queue: Queue[Event] = Queue()

    def publish(self, event: Event) -> None:
        self._queue.put_nowait(event)

    def consume(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> Event | None:
        try:
            return self._queue.get(block=block, timeout=timeout)
        except Empty:
            return None

    def task_done(self) -> None:
        self._queue.task_done()

    def join(self) -> None:
        self._queue.join()

    def empty(self) -> bool:
        return self._queue.empty()
