import asyncio
from typing import Any

from config.config import Config
from model_use.llm.base import BaseLLMProvider
from model_use.llm.deepseek import DeepSeekProvider


class LLMResponse:
    provider_classes = {
        "deepseek": DeepSeekProvider,
    }

    def __init__(self, llm_config: dict | None = None,response_format: str = None,is_streaming: bool = True) -> None:
        self.llm_config = llm_config or Config().config.get("chat_llm", {})
        self.response_format = response_format
        self.is_streaming = is_streaming
        self.provider = self.create(self.llm_config)

    def create(self, llm_config: dict) -> BaseLLMProvider:
        provider_name = llm_config.get("provider")
        provider_class = self.provider_classes.get(provider_name)
        if provider_class is None:
            supported_providers = ", ".join(self.provider_classes.keys())
            raise ValueError(
                f"Unsupported provider: {provider_name},please choose from: {supported_providers}"
            )
        return provider_class(
            api_key=llm_config.get("api_key"),
            base_url=llm_config.get("url"),
            model=llm_config.get("model"),
            is_streaming=self.is_streaming,
            response_format=self.response_format,
        )

    async def generate_response(self, prompt: dict[str, object] | str) -> Any:
        return await asyncio.to_thread(self.provider.generate_response, prompt)
