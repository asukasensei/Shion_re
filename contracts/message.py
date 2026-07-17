from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from contracts.media import Media

MESSAGE_TARGETS = {"agent", "user", "subagent", "background"}


@dataclass
class Message:
    user_id: str
    target: str = "agent"
    from_who: str = "user"
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str | None = None
    channel_id: str = "cli"
    message_id: str = field(default_factory=lambda: str(uuid4()))
    kind: str = "text"
    content: str | None = None
    media: list[Media] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.check_valid()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def check_valid(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if self.target not in MESSAGE_TARGETS:
            raise ValueError(f"Invalid target: {self.target}")
        if not self.trace_id:
            raise ValueError("trace_id is required")
        if not self.kind:
            raise ValueError("kind is required")
        if self.media is None and not isinstance(self.content, str):
            raise ValueError("Either content or media must be provided")
