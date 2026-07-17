from __future__ import annotations

from pathlib import Path
from typing import Any

from config.config import Config


class ASRService:
    """Optional OpenAI-compatible speech-to-text adapter."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = settings or Config().config.get("asr", {})
        self.enabled = bool(self.settings.get("enabled", False))
        self.model = str(self.settings.get("model") or "whisper-1")
        self.api_key = str(self.settings.get("api_key") or "")
        self.base_url = str(self.settings.get("url") or "") or None
        self.language = str(self.settings.get("language") or "zh")

    async def transcribe(self, audio_path: Path) -> str:
        if not self.enabled:
            return ""
        if not self.api_key:
            raise RuntimeError("ASR is enabled but api_key is empty")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        try:
            with audio_path.open("rb") as audio_file:
                result = await client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                    language=self.language or None,
                )
            return str(getattr(result, "text", "") or "").strip()
        finally:
            await client.close()
