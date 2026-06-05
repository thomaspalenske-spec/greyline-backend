from app.services.live_account_engine import LiveAccountEngine
from app.services.live_broker_summary_engine import LiveBrokerSummaryEngine


def test_live_account_never_enables_execution():
    result = LiveAccountEngine().get_account()

    assert result["execution_enabled"] is False
    assert result["order_placement_allowed"] is False
    assert result["account"]["execution_enabled"] is False


def test_live_broker_summary_never_enables_execution():
    result = LiveBrokerSummaryEngine().summarize()

    assert result["execution_enabled"] is False
    assert result["order_placement_allowed"] is False
