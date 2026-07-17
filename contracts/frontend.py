from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class FrontendEvent:
    """Versioned event envelope shared by FastAPI and the Electron client."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str = ""
    session_id: str = "desktop-local"
    seq: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    target_client_id: str | None = None
    v: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FrontendEvent":
        event_type = raw.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("frontend event type is required")
        payload = raw.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("frontend event payload must be an object")
        return cls(
            type=event_type,
            payload=payload,
            event_id=str(raw.get("event_id") or uuid4()),
            trace_id=str(raw.get("trace_id") or ""),
            session_id=str(raw.get("session_id") or "desktop-local"),
            seq=int(raw.get("seq") or 0),
            timestamp=str(
                raw.get("timestamp")
                or datetime.now(timezone.utc).isoformat()
            ),
            target_client_id=(
                str(raw["target_client_id"])
                if raw.get("target_client_id")
                else None
            ),
            v=int(raw.get("v") or 1),
        )
