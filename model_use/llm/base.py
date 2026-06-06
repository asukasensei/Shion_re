from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class llm_request(BaseModel):
    prompt: dict[str, Any] | str | None = None
    model: str | None = None
    format: str | None = "json_object"


class llm_response(BaseModel):
    response: dict[str, Any] | str | None = None


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate_response(self, prompt: dict[str, Any] | str) -> str:
        pass
