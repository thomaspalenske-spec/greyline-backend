from datetime import datetime
from os import getenv
import requests
from app.services.env_reload import reload_env



def _safe_json(response):
    try:
        return response.json()
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

        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            },
            timeout=20
        )

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
            "response_preview": response.text[:500],
            "response_json": _safe_json(response)
        }
