
from dataclasses import dataclass, field
from contracts.event import Event
from threading import Lock,Thread
class EventBus:
    event_bus: list[Event] = field(default_factory=list)
    running_queue: list[Event] = field(default_factory=list)
    failed_queue: list[Event] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)

    def push_event(self, event: Event) -> None:
        with self.lock:
            self.event_bus.append(event)

