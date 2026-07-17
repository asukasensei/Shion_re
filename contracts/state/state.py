from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import asyncio

from contracts.media import Media
from contracts.message import Message
from prompting.scene_prompt_dispatcher import ScenePromptDispatcher

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class State:
    user_id: str
    session_id: str
    trace_id: str
    channel_id: str
    from_who: str = "user"
    content: str | None = None
    media: list[Media] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    recent_messages: dict[str, Any] | None = field(default_factory=dict)
    session: dict[str, Any] | None = field(default_factory=dict)
    memory: dict[str, Any] | None = field(default_factory=dict)
    thoughts: dict[str, Any] | None = field(default_factory=dict)

    @classmethod
    async def from_message(cls, message: Message) -> "State":
        state = cls(
            user_id=message.user_id,
            session_id=message.session_id or message.trace_id,
            trace_id=message.trace_id,
            channel_id=message.channel_id,
            from_who=message.from_who,
            content=message.content,
            media=message.media,
            created_at=message.created_at,
        )
        await state.get_recent_messages()
        await state.get_session()
        await state.get_memory()
        return state

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    async def get_recent_messages(self, n: int = 5) -> None:
        recent = self._load_json(
            PROJECT_ROOT / ".shion" / "recent.json"
        )
        items = recent.get("items", [])
        self.recent_messages = {
            "items": [
                {
                    "date": item.get("date"),
                    "text": item.get("text"),
                }
                for item in items
                if isinstance(item, dict)
            ]
        }

    async def get_session(self) -> None:
        self.session = self._load_json(
            PROJECT_ROOT / ".shion" / "session" / "sessions.json"
        )

    async def get_memory(self) -> None:
        self.memory = {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
