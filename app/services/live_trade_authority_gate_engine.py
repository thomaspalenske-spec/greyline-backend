from datetime import datetime
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class LiveTradeAuthorityGateEngine:
    def evaluate(self):
        load_dotenv(dotenv_path=Path(".env"), override=True)

        live_execution_enabled = getenv("GREYLINE_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
        order_placement_allowed = getenv("GREYLINE_ORDER_PLACEMENT_ALLOWED", "false").lower() == "true"
        kill_switch_state = getenv("GREYLINE_KILL_SWITCH_STATE", "LOCKED").upper()

        armed = (
            live_execution_enabled is True
            and order_placement_allowed is True
            and kill_switch_state == "ARMED"
        )

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "LIVE_TRADE_AUTHORITY_GATE",
            "live_execution_enabled": live_execution_enabled,
            "order_placement_allowed": order_placement_allowed,
            "kill_switch_state": kill_switch_state,
            "authority_armed": armed,
            "status": "LIVE_TRADE_AUTHORITY_ARMED" if armed else "LIVE_TRADE_AUTHORITY_LOCKED",
        }

        ImmutableAuditLedgerEngine().record("LIVE_TRADE_AUTHORITY_GATE", result)
        return result
