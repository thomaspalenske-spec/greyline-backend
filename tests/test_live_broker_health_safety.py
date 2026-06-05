from app.services.live_broker_health_engine import LiveBrokerHealthEngine


def test_live_broker_health_never_enables_execution():
    result = LiveBrokerHealthEngine().evaluate()

    assert result["execution_enabled"] is False
    assert result["order_placement_allowed"] is False
