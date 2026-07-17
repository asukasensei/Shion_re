from behaviour.behaviour_bus import BehaviourBus
from channel.desktop import DesktopChannel
from contracts.frontend import FrontendEvent
from message.message_bus import MessageBus
from message.message_post_bus import MessagePost


def test_desktop_input_uses_shared_message_bus() -> None:
    message_bus = MessageBus()
    frontend_bus = BehaviourBus()
    channel = DesktopChannel(message_bus, frontend_bus)
    event = FrontendEvent(
        type="input.text",
        trace_id="trace-1",
        session_id="session-1",
        payload={"text": "hello", "user_id": "user-1"},
    )

    message = channel.accept_event(event, client_id="client-1")

    queued = message_bus.pop_message(timeout=0.1)
    assert message is queued
    assert queued.channel_id == "desktop"
    assert queued.trace_id == "trace-1"
    assert queued.session_id == "session-1"
    assert queued.content == "hello"


def test_desktop_output_is_published_as_frontend_event() -> None:
    frontend_bus = BehaviourBus()
    channel = DesktopChannel(MessageBus(), frontend_bus)
    subscription = frontend_bus.subscribe("client-1")
    try:
        channel.receive_message(
            MessagePost(
                channel="desktop",
                content="reply",
                trace_id="trace-1",
                session_id="session-1",
            )
        )
        event = subscription.get(0.1)
        assert event.type == "agent.delta"
        assert event.payload["content"] == "reply"
        assert event.trace_id == "trace-1"
    finally:
        subscription.close()


def test_touch_input_is_deduplicated_and_blocked_while_inflight() -> None:
    message_bus = MessageBus()
    frontend_bus = BehaviourBus()
    channel = DesktopChannel(
        message_bus,
        frontend_bus,
        touch_cooldown_ms=0,
    )
    subscription = frontend_bus.subscribe("client-1")
    first = FrontendEvent(
        type="input.touch",
        event_id="touch-1",
        trace_id="trace-touch-1",
        session_id="session-1",
        payload={"region": "head", "gesture": "tap"},
    )
    second = FrontendEvent(
        type="input.touch",
        event_id="touch-2",
        trace_id="trace-touch-2",
        session_id="session-1",
        payload={"region": "face", "gesture": "tap"},
    )

    try:
        assert channel.accept_event(first, client_id="client-1") is not None
        assert channel.accept_event(second, client_id="client-1") is None
        assert message_bus.qsize() == 1

        accepted = subscription.get(0.1)
        ignored = subscription.get(0.1)
        assert accepted is not None and accepted.type == "input.accepted"
        assert ignored is not None and ignored.type == "input.ignored"
        assert ignored.payload["reason"] == "busy"

        channel.receive_message(
            MessagePost(
                channel="desktop",
                content="",
                trace_id=first.trace_id,
                session_id=first.session_id,
                event_type="agent.done",
                is_final=True,
            )
        )
        assert channel.accept_event(first, client_id="client-1") is None

        third = FrontendEvent(
            type="input.touch",
            event_id="touch-3",
            trace_id="trace-touch-3",
            session_id="session-1",
            payload={"region": "body", "gesture": "tap"},
        )
        assert channel.accept_event(third, client_id="client-1") is not None
        assert message_bus.qsize() == 2
    finally:
        subscription.close()
