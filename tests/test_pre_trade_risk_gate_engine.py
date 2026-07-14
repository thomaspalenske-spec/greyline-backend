import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pre_trade_risk_gate_engine import PreTradeRiskGateEngine

MODULE = "app.services.pre_trade_risk_gate_engine"


def _run(broker_account_id, env):
    def fake_getenv(key, default=None):
        return env.get(key, default)

    with patch(f"{MODULE}.GreyLineConnectionWatchdogEngine") as MockWatchdog, \
         patch(f"{MODULE}.LiveBrokerSummaryEngine") as MockBroker, \
         patch(f"{MODULE}.ImmutableAuditLedgerEngine"), \
         patch(f"{MODULE}.getenv", side_effect=fake_getenv):
        MockWatchdog.return_value.run.return_value = {"overall_ready": True}
        MockBroker.return_value.summarize.return_value = {
            "account_id": broker_account_id,
            "equity": 10000,
            "buying_power": 10000,
            "snapshot_healthy": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
        }
        return PreTradeRiskGateEngine().evaluate()


def test_default_account_ok_when_broker_matches_configured_id():
    result = _run("99887766", {"TRADESTATION_MARGIN_ACCOUNT_ID": "99887766"})

    assert result["checks"]["default_account_ok"] is True


def test_default_account_not_ok_when_broker_id_differs():
    result = _run("00000000", {"TRADESTATION_MARGIN_ACCOUNT_ID": "99887766"})

    assert result["checks"]["default_account_ok"] is False


def test_fails_safe_when_account_id_not_configured():
    # No env var set -> must NOT pass (previously a hardcoded id could pass here).
    result = _run("99887766", {})

    assert result["checks"]["default_account_ok"] is False


def test_falls_back_to_ts_alias_variable():
    result = _run("55554444", {"TS_MARGIN_ACCOUNT_ID": "55554444"})

    assert result["checks"]["default_account_ok"] is True
