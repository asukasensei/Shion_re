import json
import re
import asyncio
import inspect
from typing import Any, Awaitable, Callable

from contracts.message import Message
from contracts.state.state import State
from message.message_post_bus import MessagePost
from model_use.llm_response import LLMResponse
from prompting.compose_chat import Compose
from agent.deal_response import DealResponse
from behaviour.voice.tts_base import TTSBase
from behaviour.behaviour import BehaviourData


DEFAULTCHANNEL = "cli"


BehaviourSink = Callable[[BehaviourData], Awaitable[None] | None]


class MainAgent:
    def __init__(
        self,
        output_format: str = "",
        behaviour_sink: BehaviourSink | None = None,
    ) -> None:
        self.output_format = output_format

        # chat 使用流式
        self.chat_provider = LLMResponse(
            is_streaming=True,
            response_format=output_format,
        )

        # expression task 使用非流式 JSON
        self.task_provider = LLMResponse(
            is_streaming=False,
            response_format="json_object",
        )

        self.tts = TTSBase()

        # 用于把 BehaviourData 推给外部行为系统
        # 例如：behaviour_sink = self.behaviour_bus.push
        self.behaviour_sink = behaviour_sink

    async def run(self, message: Message):
        state = State.from_message(message)
        channel_id = state.channel_id or message.channel_id or DEFAULTCHANNEL
        is_main_entry = channel_id == DEFAULTCHANNEL

        compose = Compose(state)

        chat_prompt = compose.compose_chat_prompt()
        expression_task_prompt = compose.compose_expression_task_prompt()

        # 关键：两个 prompt 同时传入两个 provider
        chat_response_task = asyncio.create_task(
            self.chat_provider.get_response(chat_prompt)
        )
        expression_response_task = asyncio.create_task(
            self.task_provider.get_response(expression_task_prompt)
        )

        # 每次 run 使用自己的 buffer 和 DealResponse，避免并发串流
        buffer: list[str] = []

        def send_chunk(chunk: str) -> None:
            if chunk and chunk.strip():
                buffer.append(chunk.strip())

        deal_response = DealResponse(send_chunk)

        expression_payload: dict[str, Any] | None = None

        try:
            chat_response = await chat_response_task

            async for delta_text in self._iter_response_text(chat_response):
                if not delta_text:
                    continue

                # 先经过 _deal_response 处理
                deal_response.feed(delta_text)

                # DealResponse 可能一次吐出多个完整文本片段
                while buffer:
                    chunk = buffer.pop(0)

                    if is_main_entry:
                        # 第一次需要时等待 expression task。
                        # 注意：任务已经提前启动，所以这里不是串行请求。
                        if expression_payload is None:
                            raw_expression_response = await expression_response_task
                            expression_payload = self._parse_expression_payload(
                                raw_expression_response
                            )

                        voice_path = await self.tts.get_voice(chunk)

                        behaviour_data = self._build_behaviour_data(
                            text=chunk,
                            voice_path=voice_path,
                            expression_payload=expression_payload,
                        )

                        await self._emit_behaviour(behaviour_data)

                    yield MessagePost(
                        channel=channel_id,
                        content=chunk,
                    )

            # 如果 DealResponse 支持 flush，建议在流结束时冲刷剩余文本
            flush = getattr(deal_response, "flush", None)
            if callable(flush):
                flush()

                while buffer:
                    chunk = buffer.pop(0)

                    if is_main_entry:
                        if expression_payload is None:
                            raw_expression_response = await expression_response_task
                            expression_payload = self._parse_expression_payload(
                                raw_expression_response
                            )

                        voice_path = await self.tts.get_voice(chunk)

                        behaviour_data = self._build_behaviour_data(
                            text=chunk,
                            voice_path=voice_path,
                            expression_payload=expression_payload,
                        )

                        await self._emit_behaviour(behaviour_data)

                    yield MessagePost(
                        channel=channel_id,
                        content=chunk,
                    )

        finally:
            # 如果 chat 中途异常，而 expression 还没结束，取消它
            if not expression_response_task.done():
                expression_response_task.cancel()

    async def _iter_response_text(self, response: Any):
        """
        兼容几种可能的 LLMResponse 返回形式：
        1. async generator
        2. 普通 generator / list
        3. 字符串
        4. dict delta
        """
        if inspect.isawaitable(response):
            response = await response

        if isinstance(response, str):
            yield response
            return

        if hasattr(response, "__aiter__"):
            async for delta in response:
                text = self._delta_to_text(delta)
                if text:
                    yield text
            return

        if hasattr(response, "__iter__"):
            for delta in response:
                text = self._delta_to_text(delta)
                if text:
                    yield text
            return

        text = self._delta_to_text(response)
        if text:
            yield text

    def _delta_to_text(self, delta: Any) -> str:
        """
        根据你的 LLMResponse 实际 delta 结构调整。
        如果你的 delta 本来就是 str，这个函数不会影响。
        """
        if delta is None:
            return ""

        if isinstance(delta, str):
            return delta

        if isinstance(delta, dict):
            return (
                delta.get("content")
                or delta.get("text")
                or delta.get("delta")
                or ""
            )

        return str(delta)

    def _parse_expression_payload(self, response: Any) -> dict[str, Any]:
        """
        expression task 必须返回 dict。
        如果 provider 返回 JSON 字符串，这里解析。
        """
        if isinstance(response, dict):
            return response

        if isinstance(response, str):
            try:
                payload = json.loads(response)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Expression task response is not valid JSON: {response}"
                ) from exc

            if not isinstance(payload, dict):
                raise ValueError(
                    f"Expression task JSON must be an object, got: {payload}"
                )

            return payload

        raise TypeError(
            f"Expected expression task response to be dict or JSON str, got: {type(response)}"
        )

    def _build_behaviour_data(
        self,
        text: str,
        voice_path: str,
        expression_payload: dict[str, Any],
    ) -> BehaviourData:
        """
        假设 expression task 返回类似：
        {
            "avatar": "happy",
            "expression_file": "/tmp/expression/happy_001.json"
        }

        如果你的字段名不是 expression_file，而是 expression_task_response_file /
        face_file / motion_file，在这里替换即可。
        """
        return BehaviourData(
            avatar=expression_payload.get("avatar", "normal"),
            voice=voice_path,
            text=text,

            # 这个字段需要 BehaviourData 类支持
            expression_file=expression_payload.get("expression_file"),
        )

    async def _emit_behaviour(self, behaviour_data: BehaviourData) -> None:
        """
        把 BehaviourData 发给行为系统。
        如果暂时没有 behaviour bus，可以先不传 behaviour_sink。
        """
        if self.behaviour_sink is None:
            return

        result = self.behaviour_sink(behaviour_data)

        if inspect.isawaitable(result):
            await result


def chunk_text(text: str) -> list[str]:
    """
    保持返回类型稳定，永远返回 list[str]。
    """
    if not text:
        return []

    return [
        x.strip()
        for x in re.split(r"[\u3002\uff01\uff1f\uff1b]", text)
        if x.strip()
    ]