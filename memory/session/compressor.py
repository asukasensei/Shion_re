from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from memory.extractor import MemoryExtractor
from memory.session.jsonl_store import JsonStore, text_length


ROOT = Path(__file__).resolve().parents[2]
SESSION_PATH = ROOT / ".shion/session/sessions.json"
RECENT_PATH = ROOT / ".shion/recent.json"
DAILY_PATH = ROOT / ".shion/daily.json"


class SessionCompressor:
    def __init__(
        self,
        session_limit: int = 1000,
        tail_limit: int = 500,
        recent_limit: int = 500,
    ) -> None:
        self.session_limit = session_limit
        self.tail_limit = tail_limit
        self.recent_limit = recent_limit
        self.sessions = JsonStore(SESSION_PATH, "turns")
        self.recent = JsonStore(RECENT_PATH, "items")
        self.daily = JsonStore(DAILY_PATH, "items")
        self.extractor = MemoryExtractor()
        self.timezone = timezone(timedelta(hours=8))

    async def append_and_compress(self, turn: dict) -> None:
        self.sessions.append(turn)
        turns = self.sessions.load()

        if text_length(turns) <= self.session_limit:
            return

        lines = await self.extractor.extract(turns)
        summary_id = str(uuid4())
        date = datetime.now(self.timezone).date().isoformat()

        entries = [
            {
                "id": f"{summary_id}:{index}",
                "summary_id": summary_id,
                "date": date,
                "text": line,
            }
            for index, line in enumerate(lines)
        ]

        # 摘要成功写入两个文件后才能删除原会话。
        self.recent.replace(self.recent.load() + entries)
        self.daily.replace(self.daily.load() + entries)

        tail = turns[-2:]
        self.sessions.replace(
            tail if text_length(tail) < self.tail_limit else []
        )
        self._trim_recent()

    def _trim_recent(self) -> None:
        items = self.recent.load()
        if text_length(items) <= self.recent_limit:
            return

        remove_count = max(1, len(items) // 2)
        self.recent.replace(items[remove_count:])
