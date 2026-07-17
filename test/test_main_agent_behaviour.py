import asyncio

from agent.main_agent import MainAgent
from behaviour.avatar.live2d_web import Live2DWebConfig, Live2DWebServer
from behaviour.behaviour import Behaviour
from contracts.message import Message


class FakeProvider:
    def __init__(self, response):
        self.response = response

    async def generate_response(self, _prompt):
        return self.response


class FakeTTS:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def get_voice(self, _text: str) -> str:
        if self.fail:
            raise RuntimeError("synthetic TTS failure")
        return ""


def test_main_agent_delivers_expression_to_behaviour_bus() -> None:
    asyncio.run(_run_main_agent_behaviour_test(tts_fails=False))


def test_tts_failure_does_not_interrupt_behaviour_or_text() -> None:
    asyncio.run(_run_main_agent_behaviour_test(tts_fails=True))


async def _run_main_agent_behaviour_test(*, tts_fails: bool) -> None:
    server = Live2DWebServer(
        Live2DWebConfig(enabled=False, auto_open=False)
    )
    subscription = server.frontend_bus.subscribe("test-client")
    agent = MainAgent(
        behaviour=Behaviour(
            behaviour_bus=server.frontend_bus,
            payload_builder=server.build_behaviour_payload,
            play_local_voice=False,
        ),
        tts=FakeTTS(fail=tts_fails),
    )
    agent.chat_provider = FakeProvider("你好。")
    agent.task_provider = FakeProvider({"expression": "happy"})
    message = Message(
        user_id="test-user",
        channel_id="desktop",
        session_id="test-session",
        trace_id="test-trace",
        from_who="system",
        content="测试",
    )

    try:
        posts = [post async for post in agent.run(message)]
        event = subscription.get(0.1)
        assert [post.content for post in posts] == ["你好。"]
        assert event is not None
        assert event.type == "behaviour.apply"
        assert event.trace_id == "test-trace"
        assert event.session_id == "test-session"
        assert event.payload["base"] == "happy"
        assert event.payload["text"] == "你好。"
    finally:
        subscription.close()
