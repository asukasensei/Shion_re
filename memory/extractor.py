import json
from typing import Any

from config.config import Config
from model_use.llm_response import LLMResponse


EXTRACT_SYSTEM_PROMPT = """
你是对话记忆精炼器。

请从对话中提取未来交流仍然有价值的信息。
要求：
1. 每条只表达一个信息。
2. 每条为一句简洁完整的话。
3. 保留用户事实、偏好、情绪、约定、关系变化和未完成事项。
4. 不记录寒暄、重复内容和无意义细节。
5. 不允许推测或虚构。
6. 使用第三人称说明主体。

只返回以下 JSON：
{"lines":["一句话","一句话"]}
"""


class MemoryExtractor:
    def __init__(self) -> None:
        work_config = Config().config["work_llm"]
        self.llm = LLMResponse(
            llm_config=work_config,
            is_streaming=False,
            response_format="json_object",
        )

    async def extract(
        self,
        turns: list[dict[str, Any]],
    ) -> list[str]:
        response = await self.llm.generate_response({
            "system": EXTRACT_SYSTEM_PROMPT,
            "user": json.dumps(turns, ensure_ascii=False),
        })

        payload = json.loads(response) if isinstance(response, str) else response
        lines = payload.get("lines", [])

        if not isinstance(lines, list):
            raise ValueError("Extractor result lines must be a list")

        result = [
            line.strip()
            for line in lines
            if isinstance(line, str) and line.strip()
        ]
        if not result:
            raise ValueError("Extractor returned no valid memory")

        return result
