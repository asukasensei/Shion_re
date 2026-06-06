from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

EVENT_PRIORITIES = {"immediate", "normal", "batch"}

@dataclass
class Event:
    priority: str
    trace_id: str
    content: str
    content_type: str
    event_id: str = field(default_factory=lambda: str(uuid4()))

