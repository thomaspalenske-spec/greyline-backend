from datetime import datetime
from os import getenv

from app.services.greyline_connection_watchdog_engine import GreyLineConnectionWatchdogEngine
from app.services.live_broker_summary_engine import LiveBrokerSummaryEngine
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class PreTradeRiskGateEngine:
    def evaluate(self, symbol="NVDA", side="BUY", quantity=1, estimated_order_value=0.0):
        watchdog = GreyLineConnectionWatchdogEngine().run()
        account = LiveBrokerSummaryEngine().summarize()

        equity = float(account.get("equity") or 0)
        buying_power = float(account.get("buying_power") or 0)

        # Expected trading account comes from config, not a hardcoded id. Fail-safe:
        # if it is not configured, default_account_ok is False and the gate blocks.
        expected_account_id = (getenv("TRADESTATION_SIM_ACCOUNT_ID")
                               or getenv("TRADESTATION_MARGIN_ACCOUNT_ID") or getenv("TS_MARGIN_ACCOUNT_ID"))

        checks = {
            "connection_ready": watchdog.get("overall_ready") is True,
            "default_account_ok": bool(expected_account_id) and account.get("account_id") == expected_account_id,
            "snapshot_healthy": account.get("snapshot_healthy") is True,
            "execution_currently_disabled": account.get("execution_enabled") is False,
            "order_placement_currently_disabled": account.get("order_placement_allowed") is False,
            "equity_positive": equity > 0,
            "buying_power_positive": buying_power > 0,
            "symbol_present": bool(symbol),
            "side_valid": side in ["BUY", "SELL"],
            "quantity_positive": quantity > 0,
            "estimated_order_value_nonnegative": estimated_order_value >= 0,
            "estimated_order_value_within_buying_power": estimated_order_value <= buying_power,
        }

        passed = all(checks.values())

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "PRE_TRADE_RISK_GATE",
            "mode": "SIMULATION_ONLY",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "estimated_order_value": estimated_order_value,
            "account_id": account.get("account_id"),
            "equity": equity,
            "buying_power": buying_power,
            "checks": checks,
            "risk_gate_passed": passed,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "PRE_TRADE_RISK_GATE_PASS_SIMULATION" if passed else "PRE_TRADE_RISK_GATE_BLOCK_SIMULATION",
        }

        ImmutableAuditLedgerEngine().record("PRE_TRADE_RISK_GATE", result)
        return result
