from __future__ import annotations

import json
import asyncio
import sys
import urllib.request
from pathlib import Path

import websockets


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from behaviour.avatar.live2d_web import (  # noqa: E402
    DEFAULT_MODEL_DIR,
    DEFAULT_MODEL_FILE,
    Live2DWebConfig,
    Live2DWebServer,
)
from behaviour.behaviour import Behaviour, BehaviourData  # noqa: E402
from event.event_bus import EventBus  # noqa: E402
from message.message_bus import MessageBus  # noqa: E402
from message.message_post_bus import MessagePost, MessagePostBus  # noqa: E402
from runtime.dispatcher import Dispatcher  # noqa: E402


def test_live2d_web_server_serves_page_and_model() -> None:
    server = Live2DWebServer(
        Live2DWebConfig(
            enabled=True,
            auto_open=False,
            host="127.0.0.1",
            port=0,
            model_dir=DEFAULT_MODEL_DIR,
            model_file=DEFAULT_MODEL_FILE,
            touch_cooldown_ms=1500,
            persistent_parameters={"Param221": 1.0},
        )
    )
    try:
        url = server.start(open_browser=False)
        assert url is not None

        with urllib.request.urlopen(url, timeout=3) as response:
            html = response.read().decode("utf-8")
        assert "live2d-canvas" in html
        assert "script-src 'self' 'unsafe-eval'" in html
        assert 'src="/renderer/renderer.bundle.js"' in html
        assert 'src="/vendor/pixi.min.js"' not in html

        for asset in (
            "vendor/live2dcubismcore.min.js",
            "renderer/renderer.bundle.js",
        ):
            with urllib.request.urlopen(url + asset, timeout=3) as response:
                assert response.status == 200
                assert int(response.headers["content-length"]) > 0

        model_url = url + "live2d-model/%E6%99%B4%E9%9B%A8.model3.json"
        with urllib.request.urlopen(model_url, timeout=3) as response:
            model = json.loads(response.read().decode("utf-8"))
        assert model["FileReferences"]["Moc"] == "\u6674\u96e8.moc3"

        client_config = server.client_config()
        assert client_config["touch_cooldown_ms"] == 1500
        assert client_config["persistent_parameters"] == {"Param221": 1.0}
    finally:
        server.stop()


def test_live2d_websocket_routes_desktop_input() -> None:
    asyncio.run(_test_live2d_websocket_routes_desktop_input())


async def _test_live2d_websocket_routes_desktop_input() -> None:
    message_bus = MessageBus()
    server = Live2DWebServer(
        Live2DWebConfig(
            enabled=True,
            auto_open=False,
            launch_electron=False,
            host="127.0.0.1",
            port=0,
            model_dir=DEFAULT_MODEL_DIR,
            model_file=DEFAULT_MODEL_FILE,
        ),
        message_bus=message_bus,
    )
    try:
        url = server.start(open_browser=False)
        assert url is not None
        websocket_url = (
            url.replace("http://", "ws://")
            + "ws/desktop?client_id=test-client&token="
            + server.client_config()["token"]
        )
        async with websockets.connect(websocket_url) as socket:
            await socket.send(
                json.dumps(
                    {
                        "v": 1,
                        "type": "input.text",
                        "event_id": "event-1",
                        "trace_id": "trace-1",
                        "session_id": "session-1",
                        "payload": {"text": "hello", "user_id": "user-1"},
                    }
                )
            )
            for _ in range(5):
                event = json.loads(await asyncio.wait_for(socket.recv(), 2))
                if event["type"] == "input.accepted":
                    break
            else:
                raise AssertionError("input.accepted was not received")

            message = message_bus.pop_message(timeout=1)
            assert message is not None
            assert message.channel_id == "desktop"
            assert message.session_id == "session-1"
            assert message.trace_id == "trace-1"
            assert message.content == "hello"
    finally:
        server.stop()


def test_desktop_round_trip_delivers_text_expression_and_voice(tmp_path: Path) -> None:
    asyncio.run(_test_desktop_round_trip(tmp_path))


async def _test_desktop_round_trip(tmp_path: Path) -> None:
    message_bus = MessageBus()
    message_post_bus = MessagePostBus()
    server = Live2DWebServer(
        Live2DWebConfig(
            enabled=True,
            auto_open=False,
            launch_electron=False,
            host="127.0.0.1",
            port=0,
            model_dir=DEFAULT_MODEL_DIR,
            model_file=DEFAULT_MODEL_FILE,
        ),
        message_bus=message_bus,
    )
    voice_path = tmp_path / "reply.mp3"
    voice_path.write_bytes(b"synthetic-audio")
    behaviour = Behaviour(
        behaviour_bus=server.frontend_bus,
        payload_builder=server.build_behaviour_payload,
        play_local_voice=False,
    )

    class FakeMainAgent:
        def __init__(self) -> None:
            self.received = []

        async def run(self, message):
            self.received.append(message)
            await behaviour.play_behaviour(
                BehaviourData(
                    avatar={"expression": "happy"},
                    voice=str(voice_path),
                    text="桌面回复",
                    trace_id=message.trace_id,
                    session_id=message.session_id or message.trace_id,
                )
            )
            yield MessagePost(channel=message.channel_id, content="桌面回复")

    agent = FakeMainAgent()
    dispatcher = Dispatcher(
        message_bus=message_bus,
        message_post_bus=message_post_bus,
        event_bus=EventBus(),
        main_agent=agent,
    )

    try:
        url = server.start(open_browser=False)
        assert url is not None
        token = server.client_config()["token"]
        websocket_base = url.replace("http://", "ws://") + "ws/desktop"
        control_url = websocket_base + f"?client_id=control-test&token={token}"
        avatar_url = websocket_base + f"?client_id=avatar-test&token={token}"

        async with (
            websockets.connect(control_url) as control,
            websockets.connect(avatar_url) as avatar,
        ):
            await control.send(
                json.dumps(
                    {
                        "v": 1,
                        "type": "input.text",
                        "event_id": "round-trip-event",
                        "trace_id": "round-trip-trace",
                        "session_id": "round-trip-session",
                        "payload": {"text": "桌面输入", "user_id": "desktop-user"},
                    }
                )
            )
            accepted = await _receive_event(control, "input.accepted")
            assert accepted["trace_id"] == "round-trip-trace"

            assert await asyncio.to_thread(dispatcher.dispatch_once, False, 0)
            while True:
                post = message_post_bus.pop_message(block=False)
                if post is None:
                    break
                try:
                    server.desktop_channel.receive_message(post)
                finally:
                    message_post_bus.task_done()

            avatar_events = {
                event_type: await _receive_event(avatar, event_type)
                for event_type in ("behaviour.apply", "agent.delta", "agent.done")
            }
            behaviour_event = avatar_events["behaviour.apply"]
            assert behaviour_event["trace_id"] == "round-trip-trace"
            assert behaviour_event["session_id"] == "round-trip-session"
            assert behaviour_event["payload"]["base"] == "happy"
            assert behaviour_event["payload"]["text"] == "桌面回复"
            assert behaviour_event["payload"]["audio_url"].startswith(
                "/media/audio/"
            )
            assert avatar_events["agent.delta"]["payload"]["content"] == "桌面回复"
            assert agent.received[0].content == "桌面输入"
            assert agent.received[0].channel_id == "desktop"
    finally:
        server.stop()


async def _receive_event(socket, event_type: str) -> dict:
    for _ in range(12):
        event = json.loads(await asyncio.wait_for(socket.recv(), 2))
        if event["type"] == event_type:
            return event
    raise AssertionError(f"Event {event_type!r} was not received")
