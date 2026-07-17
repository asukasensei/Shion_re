# prompting/scene_prompt_dispatcher.py
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHION_DIR = PROJECT_ROOT / ".shion"


@dataclass(frozen=True)
class SceneDispatchResult:
    strategy_prompt: str
    avatar: dict[str, Any]
    matched_rule: dict[str, Any] | None = None


class ScenePromptDispatcher:
    """
    根据 scene / emotion / intensity 从用户数据库中读取回答策略与表情策略。

    默认数据库:
        .shion/{user_id}.db

    例如 user_id = "01":
        .shion/01.db
    """

    def __init__(
        self,
        user_id: str = "01",
        db_path: str | Path | None = None,
    ) -> None:
        self.user_id = user_id
        self.db_path = Path(db_path) if db_path else SHION_DIR / f"{user_id}.db"
        self._ensure_db()

    def dispatch(
        self,
        emotion: str | None = None,
        scene: str | None = None,
        intensity: int | None = None,
        source: str = "router",
    ) -> SceneDispatchResult:
        rule = self._find_best_rule(
            scene=scene,
            emotion=emotion,
            intensity=intensity,
        )

        if rule is None:
            return self._fallback(
                scene=scene,
                emotion=emotion,
                intensity=intensity,
                source=source,
            )

        avatar = self._parse_avatar(rule.get("avatar_json"))
        avatar.setdefault("scene", scene)
        avatar.setdefault("emotion", emotion)
        avatar.setdefault("intensity", intensity)
        avatar.setdefault("source", source)

        return SceneDispatchResult(
            strategy_prompt=rule["strategy_prompt"],
            avatar=avatar,
            matched_rule=rule,
        )

    def _ensure_db(self) -> None:
        SHION_DIR.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scene_prompt_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scene TEXT,
                    emotion TEXT,
                    intensity_min INTEGER,
                    intensity_max INTEGER,
                    strategy_prompt TEXT NOT NULL,
                    avatar_json TEXT,
                    priority INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scene_prompt_rules_match
                ON scene_prompt_rules (
                    enabled,
                    scene,
                    emotion,
                    intensity_min,
                    intensity_max,
                    priority
                )
                """
            )

            self._seed_defaults_if_empty(conn)

    def _seed_defaults_if_empty(self, conn: sqlite3.Connection) -> None:
        count = conn.execute(
            "SELECT COUNT(*) FROM scene_prompt_rules"
        ).fetchone()[0]

        if count:
            return

        defaults = [
            {
                "scene": "daily_chat",
                "emotion": None,
                "intensity_min": None,
                "intensity_max": None,
                "strategy_prompt": "本轮采用轻松、自然、短句的日常聊天策略。可以有一点好奇、打趣或亲近感，但不要过度展开。",
                "avatar": {"expression": "normal"},
                "priority": 10,
                "note": "默认日常聊天策略",
            },
            {
                "scene": "emotional_support",
                "emotion": None,
                "intensity_min": None,
                "intensity_max": None,
                "strategy_prompt": "本轮优先承接用户情绪。先表达理解和陪伴，再给出很轻的小建议。不要急着讲道理，不要把回复写得太正式。",
                "avatar": {"expression": "sad"},
                "priority": 20,
                "note": "默认情绪支持策略",
            },
            {
                "scene": "task_request",
                "emotion": None,
                "intensity_min": None,
                "intensity_max": None,
                "strategy_prompt": "本轮优先识别用户想完成的具体任务，回复要直接、清楚。可以先给结论，再补充必要步骤。",
                "avatar": {"expression": "normal"},
                "priority": 20,
                "note": "默认任务策略",
            },
            {
                "scene": "relationship",
                "emotion": "affection",
                "intensity_min": None,
                "intensity_max": None,
                "strategy_prompt": "本轮可以更温柔、更亲近一些。回应里允许表达自己的在意，但保持自然，不要变成夸张告白。",
                "avatar": {"expression": "happy"},
                "priority": 40,
                "note": "亲密关系 + 好感表达",
            },
            {
                "scene": None,
                "emotion": "sadness",
                "intensity_min": None,
                "intensity_max": None,
                "strategy_prompt": "用户情绪偏低落。本轮回复要柔软、低压，先陪着他/她，不要急着解决问题。",
                "avatar": {"expression": "sad"},
                "priority": 30,
                "note": "悲伤情绪兜底",
            },
            {
                "scene": None,
                "emotion": "joy",
                "intensity_min": None,
                "intensity_max": None,
                "strategy_prompt": "用户情绪偏开心。本轮可以更轻快一点，分享他的/她的开心，也可以自然地开个小玩笑。",
                "avatar": {"expression": "happy"},
                "priority": 30,
                "note": "开心情绪兜底",
            },
        ]

        for item in defaults:
            conn.execute(
                """
                INSERT INTO scene_prompt_rules (
                    scene,
                    emotion,
                    intensity_min,
                    intensity_max,
                    strategy_prompt,
                    avatar_json,
                    priority,
                    note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["scene"],
                    item["emotion"],
                    item["intensity_min"],
                    item["intensity_max"],
                    item["strategy_prompt"],
                    json.dumps(item["avatar"], ensure_ascii=False),
                    item["priority"],
                    item["note"],
                ),
            )

    def _find_best_rule(
        self,
        scene: str | None,
        emotion: str | None,
        intensity: int | None,
    ) -> dict[str, Any] | None:
        """
        匹配优先级:
        1. scene + emotion + intensity 区间完全匹配
        2. scene + emotion
        3. scene
        4. emotion
        5. priority 高者优先
        """

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                """
                SELECT *
                FROM scene_prompt_rules
                WHERE enabled = 1
                  AND (scene IS NULL OR scene = ?)
                  AND (emotion IS NULL OR emotion = ?)
                  AND (
                        ? IS NULL
                        OR intensity_min IS NULL
                        OR intensity_min <= ?
                  )
                  AND (
                        ? IS NULL
                        OR intensity_max IS NULL
                        OR intensity_max >= ?
                  )
                """,
                (
                    scene,
                    emotion,
                    intensity,
                    intensity,
                    intensity,
                    intensity,
                ),
            ).fetchall()

        if not rows:
            return None

        scored = []
        for row in rows:
            rule = dict(row)
            score = self._match_score(rule, scene, emotion, intensity)
            scored.append((score, rule))

        scored.sort(
            key=lambda item: (
                item[0],
                item[1]["priority"],
                item[1]["id"],
            ),
            reverse=True,
        )

        return scored[0][1]

    def _match_score(
        self,
        rule: dict[str, Any],
        scene: str | None,
        emotion: str | None,
        intensity: int | None,
    ) -> int:
        score = 0

        if rule.get("scene") is not None and rule.get("scene") == scene:
            score += 100

        if rule.get("emotion") is not None and rule.get("emotion") == emotion:
            score += 80

        if intensity is not None:
            has_min = rule.get("intensity_min") is not None
            has_max = rule.get("intensity_max") is not None
            if has_min or has_max:
                score += 40

        return score

    def _parse_avatar(self, avatar_json: str | None) -> dict[str, Any]:
        if not avatar_json:
            return {"expression": "normal"}

        try:
            avatar = json.loads(avatar_json)
        except json.JSONDecodeError:
            return {"expression": "normal"}

        if not isinstance(avatar, dict):
            return {"expression": "normal"}

        avatar.setdefault("expression", "normal")
        return avatar

    def _fallback(
        self,
        scene: str | None,
        emotion: str | None,
        intensity: int | None,
        source: str,
    ) -> SceneDispatchResult:
        expression_map = {
            "joy": "happy",
            "sadness": "sad",
            "anger": "angry",
            "anxiety_fear": "sad",
            "frustration": "sad",
            "loneliness": "sad",
            "shame_embarrassment": "normal",
            "affection": "happy",
            "surprise": "happy",
            "tiredness": "normal",
            "neutral": "normal",
        }

        return SceneDispatchResult(
            strategy_prompt="",
            avatar={
                "expression": expression_map.get(emotion or "", "normal"),
                "scene": scene,
                "emotion": emotion,
                "intensity": intensity,
                "source": source,
            },
            matched_rule=None,
        )