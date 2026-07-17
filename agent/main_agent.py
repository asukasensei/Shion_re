import json
import asyncio
import logging
from typing import Any, Awaitable
import inspect

from contracts.message import Message
from contracts.state.state import State
from message.message_post_bus import MessagePost
from model_use.llm_response import LLMResponse
from prompting.compose_chat import Compose
from agent.deal_response import DealResponse
from behaviour.voice.tts_base import TTSBase
from behaviour.behaviour import BehaviourData, Behaviour
from route.route import BGERouteClassifier


DEFAULTCHANNEL = "cli"
MAIN_CHANNELS = {"cli", "desktop"}
logger = logging.getLogger(__name__)


class MainAgent:
    def __init__(
        self,
        output_format: str = "",
        behaviour: Behaviour | None = None,
        tts: TTSBase | None = None,
        route: BGERouteClassifier | None = None,
    ) -> None:
        self.output_format = output_format
        self.chat_provider = LLMResponse(is_streaming=True, response_format=output_format)
        self.task_provider = LLMResponse(is_streaming=False, response_format="json_object")
        self.behaviour = behaviour or Behaviour()
        self.scene_dispatcher: Any | None = None
        self.route: Any | None = None
        self.tts = tts or TTSBase()
        self.route = route or BGERouteClassifier()


    async def run(self, message: Message):
        state = await State.from_message(message)
        channel_id = state.channel_id or message.channel_id or DEFAULTCHANNEL
        is_main_entry = channel_id in MAIN_CHANNELS
        compose = Compose(state)
        chat_prompt = compose.compose_chat_prompt()
        if state.from_who == "user":
            scene_strategy = self._dispatch_scene_strategy(state)
            if scene_strategy:
                chat_prompt["response_strategy"] = scene_strategy

        expression_task_prompt = compose.compose_expression_task_prompt()
        # 关键：两个 prompt 同时传入两个 provider
        chat_response_task = asyncio.create_task(
            self.chat_provider.generate_response(chat_prompt)
        )
        expression_response_task = asyncio.create_task(
            self.task_provider.generate_response(expression_task_prompt)
        )
        buffer: list[str] = []
        expression_payload: dict[str, Any] | None = None
        expression_response_retrieved = False

        def send_chunk(chunk: str) -> None:
            if chunk and chunk.strip():
                buffer.append(chunk.strip())

        deal_response = DealResponse(send_chunk)

        async def process_buffered_chunks():
            nonlocal expression_payload
            nonlocal expression_response_retrieved

            while buffer:
                chunk = buffer.pop(0)
                if is_main_entry:
                    voice_task = asyncio.create_task(
                        asyncio.to_thread(self.tts.get_voice, chunk)
                    )
                    if expression_payload is None:
                        try:
                            raw_expression_response = await expression_response_task
                            expression_response_retrieved = True
                            expression_payload = self._parse_expression_payload(
                                raw_expression_response
                            )
                        except Exception:
                            expression_response_retrieved = True
                            expression_payload = {"expression": "normal"}
                            logger.exception(
                                "Expression generation failed for trace %s",
                                message.trace_id,
                            )
                    try:
                        voice_path = await voice_task
                    except Exception:
                        voice_path = ""
                        logger.exception(
                            "TTS generation failed for trace %s",
                            message.trace_id,
                        )
                    behaviour_data = BehaviourData(
                        text=chunk,
                        voice=voice_path,
                        avatar=expression_payload,
                        trace_id=message.trace_id,
                        session_id=message.session_id or message.trace_id,
                    )
                    try:
                        await self._emit_behaviour(behaviour_data)
                    except Exception:
                        logger.exception(
                            "Behaviour delivery failed for trace %s",
                            message.trace_id,
                        )

                yield MessagePost(
                    channel=channel_id,
                    content=chunk,
                )

        try:
            chat_response = await chat_response_task
            async for delta_text in self._iter_response_text(chat_response):
                if not delta_text:
                    continue
                deal_response.feed(delta_text)

                async for post in process_buffered_chunks():
                    yield post

            deal_response.flush()
            async for post in process_buffered_chunks():
                yield post
        finally:
            # 如果 chat 中途异常，而 expression 还没结束，取消它
            if not expression_response_task.done():
                expression_response_task.cancel()
            if not expression_response_retrieved:
                try:
                    await expression_response_task
                except (asyncio.CancelledError, Exception):
                    pass

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
 
    
    def _emit_behaviour(self, behaviour_data: BehaviourData) -> Awaitable[None]:
        return self.behaviour.play_behaviour(behaviour_data)


    def _dispatch_scene_strategy(self, state: State) -> str | None:
        try:
            if self.route is None:
                from route.route import Route

                self.route = Route()
            route_result = self.route.dispatch(state)
            if not route_result:
                return None

            if self.scene_dispatcher is None:
                from prompting.scene_prompt_dispatcher import ScenePromptDispatcher

                self.scene_dispatcher = ScenePromptDispatcher()
            scene_result = self.scene_dispatcher.dispatch(route_result)
            return getattr(scene_result, "strategy_prompt", None)
        except (ImportError, AttributeError, FileNotFoundError):
            return None
