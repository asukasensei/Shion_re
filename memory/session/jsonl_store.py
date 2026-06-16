# memory/session/jsonl_store.py
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def text_length(value: Any) -> int:
    if isinstance(value, dict):
        ignored_keys = {"id", "summary_id", "date", "time"}
        return sum(
            text_length(item)
            for key, item in value.items()
            if key not in ignored_keys
        )
    if isinstance(value, list):
        return sum(text_length(item) for item in value)
    if isinstance(value, str):
        return len(re.sub(r"\s+", "", value))
    return 0


class JsonStore:
    def __init__(self, path: Path, root_key: str) -> None:
        self.path = path
        self.root_key = root_key
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []

        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(f"{self.path} must contain a JSON object")

        items = data.get(self.root_key, [])
        if not isinstance(items, list):
            raise ValueError(
                f"{self.path}: {self.root_key!r} must be a list"
            )
        return items

    def replace(self, items: list[dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(
                {self.root_key: items},
                file,
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.path)

    def append(self, item: dict[str, Any]) -> None:
        items = self.load()
        items.append(item)
        self.replace(items)


DEFAULT_JSONL_PATH = Path(".Shion/session/sessions.jsonl")
class JsonlConversationStore:
    def __init__(self, path: Path = DEFAULT_JSONL_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, turn: dict[str, Any]) -> None:
        line = json.dumps(
            turn,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )

        with self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

    async def close(self) -> None:
        pass
