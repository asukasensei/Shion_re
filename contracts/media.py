from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class Media:
    url: str | None = None
    path: str | None = None
    type: str | None = None


