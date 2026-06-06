from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from contracts.media import Media
from contracts.message import Message

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class State:
    user_id: str
    session_id: str
    trace_id: str
    channel_id: str
    content: str | None = None
    media: list[Media] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    recent_messages: dict[str, Any] | None = field(default_factory=dict)
    session: dict[str, Any] | None = field(default_factory=dict)
    memory: dict[str, Any] | None = field(default_factory=dict)
    thoughts: dict[str, Any] | None = field(default_factory=dict)

    @classmethod
    def from_message(cls, message: Message) -> "State":
        state = cls(
            user_id=message.user_id,
            session_id=message.trace_id,
            trace_id=message.trace_id,
            channel_id=message.channel_id,
            content=message.content,
            media=message.media,
            created_at=message.created_at,
        )
        state.get_recent_messages()
        state.get_session()
        state.get_memory()
        return state

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def get_recent_messages(self, n: int = 5) -> None:
        self.recent_messages = self._load_json(PROJECT_ROOT / "memory" / "recent" / "recent.json")

    def get_session(self) -> None:
        self.session = self._load_json(PROJECT_ROOT / "memory" / "recent" / "session.json")

    def get_memory(self) -> None:
        self.memory = {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
