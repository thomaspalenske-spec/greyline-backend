from datetime import datetime
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine
from app.services.live_order_safety_guard_engine import (
    broker_base_url,
    classify_broker_endpoint,
)


class LiveTradeAuthorityGateEngine:
    def evaluate(self):
        load_dotenv(dotenv_path=Path(".env"), override=True)

        live_execution_enabled = getenv("GREYLINE_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
        order_placement_allowed = getenv("GREYLINE_ORDER_PLACEMENT_ALLOWED", "false").lower() == "true"
        kill_switch_state = getenv("GREYLINE_KILL_SWITCH_STATE", "LOCKED").upper()

        # Production endpoint safety: never arm live authority against a PRODUCTION
        # broker host unless the operator has explicitly confirmed it.
        base_url = broker_base_url()
        endpoint_env = classify_broker_endpoint(base_url)
        production_confirmed = getenv("GREYLINE_LIVE_PRODUCTION_CONFIRMED", "false").lower() == "true"
        endpoint_safe = endpoint_env == "SANDBOX" or (
            endpoint_env == "PRODUCTION" and production_confirmed
        )

        armed = (
            live_execution_enabled is True
            and order_placement_allowed is True
            and kill_switch_state == "ARMED"
            and endpoint_safe is True
        )

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "LIVE_TRADE_AUTHORITY_GATE",
            "live_execution_enabled": live_execution_enabled,
            "order_placement_allowed": order_placement_allowed,
            "kill_switch_state": kill_switch_state,
            "endpoint_env": endpoint_env,
            "production_confirmed": production_confirmed,
            "endpoint_safe": endpoint_safe,
            "authority_armed": armed,
            "status": "LIVE_TRADE_AUTHORITY_ARMED" if armed else "LIVE_TRADE_AUTHORITY_LOCKED",
        }

        ImmutableAuditLedgerEngine().record("LIVE_TRADE_AUTHORITY_GATE", result)
        return result
