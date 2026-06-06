import json

from openai import OpenAI

from model_use.llm.base import BaseLLMProvider


class DeepSeekProvider(BaseLLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        is_streaming: bool = True,
        response_format: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeek api_key is required")
        self.api_key = api_key
        self.base_url = base_url or "https://api.deepseek.com"
        self.model = model or "deepseek-v4-flash"
        self.is_streaming = is_streaming
        self.response_format = response_format
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate_response(self, prompt: dict[str, object] | str):
        kwargs = {
            "model": self.model,
            "messages": self._to_messages(prompt),
            "stream": self.is_streaming,
        }
        if self.response_format:
            kwargs["response_format"] = {"type": self.response_format}

        response = self.client.chat.completions.create(**kwargs)
        if self.is_streaming:
            return self._iter_stream(response)
        return response.choices[0].message.content or ""

    @staticmethod
    def _iter_stream(response):
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def _to_messages(self, prompt: dict[str, object] | str) -> list[dict[str, str]]:
        if isinstance(prompt, str):
            return [{"role": "user", "content": prompt}]

        messages: list[dict[str, str]] = []
        system = prompt.get("system")
        if system:
            messages.append({"role": "system", "content": str(system)})

        context_parts = []
        for key in ("memory", "recent_messages", "session", "media"):
            value = prompt.get(key)
            if value:
                context_parts.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")

        user = str(prompt.get("user") or "")
        if context_parts:
            user = "\n".join(context_parts) + f"\nuser: {user}"
        messages.append({"role": "user", "content": user})
        return messages
