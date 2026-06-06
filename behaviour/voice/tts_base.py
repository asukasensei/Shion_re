from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from config.config import Config


class BaseTTSProvider(ABC):
    @abstractmethod
    def get_voice(self, text: str, output_path: str | Path | None = None) -> str:
        pass

    def close(self) -> None:
        pass


class TTSBase:
    provider_classes: dict[str, type[BaseTTSProvider]] = {}

    def __init__(self, tts_config: dict[str, Any] | None = None):
        self.tts_config = tts_config or Config().config.get("tts", {})
        self.provider = self.create(self.tts_config)

    @classmethod
    def _load_provider_classes(cls) -> dict[str, type[BaseTTSProvider]]:
        if not cls.provider_classes:
            from behaviour.voice.qwen import QwenTTSProvider

            cls.provider_classes = {
                "qwen": QwenTTSProvider,
            }
        return cls.provider_classes

    def create(self, tts_config: dict[str, Any]) -> BaseTTSProvider:
        provider_name = tts_config.get("provider") or tts_config.get("procider")
        provider_class = self._load_provider_classes().get(provider_name)
        if provider_class is None:
            supported_providers = ", ".join(self._load_provider_classes().keys())
            raise ValueError(
                f"Unsupported TTS provider: {provider_name}, "
                f"please choose from: {supported_providers}"
            )
        return provider_class(tts_config)

    def get_voice(self, text: str, output_path: str | Path | None = None) -> str:
        voice_path = self.provider.get_voice(text, output_path)
        print(f"voice generated: {voice_path}")
        return voice_path

    def close(self) -> None:
        self.provider.close()

    def __enter__(self) -> "TTSBase":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
