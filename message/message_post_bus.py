from dataclasses import dataclass
from queue import Empty, Queue


@dataclass
class MessagePost:
    channel: str
    content: str
    trace_id: str = ""
    session_id: str = ""
    user_id: str = ""
    message_id: str = ""
    event_type: str = "agent.delta"
    is_final: bool = False


class MessagePostBus:
    def __init__(self) -> None:
        self._queue: Queue[MessagePost] = Queue()

    def push_message(self, message: MessagePost) -> None:
        self._queue.put(message)

    def pop_message(self, block: bool = True, timeout: float | None = None) -> MessagePost | None:
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
