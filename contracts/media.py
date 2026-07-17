from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class Media:
    media_id: str | None = None
    url: str | None = None
    path: str | None = None
    type: str | None = None
    mime_type: str | None = None
    size: int | None = None
    duration_ms: int | None = None
    transcript: str | None = None


