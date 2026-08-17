import json
from datetime import datetime
from os import getenv
import requests
from app.services.env_reload import reload_env
from app.services.http_bounded import bounded_get, envf


def _safe_json(body):
    try:
        return json.loads(body) if body else None
    except Exception:
        return None


class TradeStationOrdersLiveEngine:

    def __init__(self):
        reload_env()

    def get_orders(self):
        from app.services.tradestation_account_source_engine import TradeStationAccountSourceEngine
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        # WHICH account (paper vs live) is decided by the one selector, not here.
        src = TradeStationAccountSourceEngine().resolve()
        account_id = src.get("account_id")
        base_url = src.get("base_url")

        if not src.get("ok") or not access_token or not account_id:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "orders_attempted": False,
                "execution_enabled": False,
                "account_mode": src.get("mode"),
                "status": src.get("error") or "ACCESS_TOKEN_OR_ACCOUNT_ID_REQUIRED"
            }

        url = base_url.rstrip("/") + f"/v3/brokerage/accounts/{account_id}/orders"

        # TOTAL-DEADLINE bounded read (full trickle-immunity): requests' timeout is only between-bytes, so a
        # trickling/half-open TS response would hang the caller — bounded_get aborts at a wall-clock deadline
        # and any failure returns a DEGRADED dict (http_status None) so the snapshot fails-closed, never hangs.
        try:
            response, body = bounded_get(
                requests, url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                connect_timeout=envf("GREYLINE_TS_BROKER_CONNECT_TIMEOUT", 5.0),
                read_timeout=envf("GREYLINE_TS_BROKER_READ_TIMEOUT", 8.0),
                total_deadline=envf("GREYLINE_TS_BROKER_DEADLINE", 15.0))
        except Exception as error:
            return {
                "timestamp": datetime.utcnow().isoformat(), "broker": "TradeStation",
                "orders_attempted": True, "http_status": None, "execution_enabled": False,
                "account_mode": src.get("mode"), "account_id": account_id, "host_kind": src.get("host_kind"),
                "status": "ORDERS_READ_FAILED", "error": str(error)[:200], "response_json": None,
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "orders_attempted": True,
            "http_status": response.status_code,
            "execution_enabled": False,
            "account_mode": src.get("mode"),
            "account_id": account_id,
            "host_kind": src.get("host_kind"),
            "status": "ORDERS_READ_SUCCESS" if response.status_code == 200 else "ORDERS_READ_FAILED",
            "response_preview": (body[:500].decode("utf-8", "replace") if body else ""),
            "response_json": _safe_json(body)
        }
