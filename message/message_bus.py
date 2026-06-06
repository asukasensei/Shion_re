from queue import Empty, Queue

from contracts.message import Message


class MessageBus:
    def __init__(self) -> None:
        self._queue: Queue[Message] = Queue()

    def push_message(self, message: Message) -> None:
        self._queue.put(message)

    def pop_message(self, block: bool = True, timeout: float | None = None) -> Message | None:
        try:
            return self._queue.get(block=block, timeout=timeout)
        except Empty:
            return None

    def task_done(self) -> None:
        self._queue.task_done()

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()
