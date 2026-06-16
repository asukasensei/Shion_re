import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.config import Config
from memory.session.jsonl_store import JsonStore
from model_use.llm_response import LLMResponse


ROOT = Path(__file__).resolve().parents[2]

DIARY_SYSTEM_PROMPT = """
你是汐音，请根据昨天的记录写一篇精炼日记。
重点包括：
- 我和用户的关系发生了什么变化。
- 我对用户的看法发生了什么变化。
- 我新了解了用户哪些方面。
- 我还想了解用户什么。
- 接下来我想和用户做什么。
不得虚构，语言自然简洁，不要逐条复述原对话。

"""


class DiaryService:
    def __init__(self) -> None:
        self.daily = JsonStore(ROOT / ".shion/daily.json", "items")
        self.sessions = JsonStore(
            ROOT / ".shion/session/sessions.json", "turns"
        )
        self.diary_dir = ROOT / ".shion/diary"
        self.state_path = ROOT / ".shion/memory_state.json"
        self.timezone = timezone(timedelta(hours=8))
        self.llm = LLMResponse(
            llm_config=Config().config["work_llm"],
            is_streaming=False,
        )

    async def process_if_new_day(self) -> None:
        today = datetime.now(self.timezone).date().isoformat()
        previous_launch = self._load_last_launch()

        if previous_launch is None:
            self._save_last_launch(today)
            return
        if previous_launch == today:
            return

        source = {
            "daily": self.daily.load(),
            "remaining_sessions": self.sessions.load(),
        }

        if source["daily"] or source["remaining_sessions"]:
            diary = await self.llm.generate_response({
                "system": DIARY_SYSTEM_PROMPT,
                "user": json.dumps(source, ensure_ascii=False),
            })

            self.diary_dir.mkdir(parents=True, exist_ok=True)
            diary_path = self.diary_dir / f"{previous_launch}.md"
            diary_path.write_text(str(diary).strip(), encoding="utf-8")

            # 日记成功落盘后才清理来源。
            self.daily.replace([])
            self.sessions.replace([])

        self._save_last_launch(today)

    def _load_last_launch(self) -> str | None:
        if not self.state_path.exists():
            return None
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data.get("last_launch_date")

    def _save_last_launch(self, date: str) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {"last_launch_date": date},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
