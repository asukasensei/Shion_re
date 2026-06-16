# contracts/event.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


EVENT_PRIORITIES = {"immediate", "normal", "batch"}


@dataclass(frozen=True, slots=True)
class Event:
    event_type: str
    content: Any
    priority: str = "normal"
    event_id: str = field(default_factory=lambda: str(uuid4()))
    attempts: int = 0


    def __post_init__(self) -> None:
        if self.priority not in EVENT_PRIORITIES:
            raise ValueError(f"Invalid event priority: {self.priority}")
        if not self.event_type:
            raise ValueError("event_type is required")
