from behaviour.behaviour_bus import BehaviourBus


def test_behaviour_bus_routes_and_replays_targeted_events() -> None:
    bus = BehaviourBus(history_size=8, subscriber_size=8)
    bus.publish_event("broadcast", {"value": 1})
    bus.publish_event("private", {"value": 2}, target_client_id="a")

    subscription_a = bus.subscribe("a", after_seq=0)
    subscription_b = bus.subscribe("b", after_seq=0)
    try:
        assert subscription_a.get(0.1).type == "broadcast"
        assert subscription_a.get(0.1).type == "private"
        assert subscription_b.get(0.1).type == "broadcast"
        assert subscription_b.get(0.01) is None
    finally:
        subscription_a.close()
        subscription_b.close()
