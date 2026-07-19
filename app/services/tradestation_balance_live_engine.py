from datetime import datetime
from os import getenv
import requests
from app.services.env_reload import reload_env



def _safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


class TradeStationBalanceLiveEngine:

    def __init__(self):
        reload_env()

    def get_balance(self):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        # Prefer the simulated account so reads resolve on the sandbox host. The real
        # margin account is only a fallback (and only reachable via the production URL).
        account_id = getenv("TRADESTATION_SIM_ACCOUNT_ID") or getenv("TRADESTATION_MARGIN_ACCOUNT_ID", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")

        if not access_token or not account_id:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "balance_attempted": False,
                "execution_enabled": False,
                "status": "ACCESS_TOKEN_OR_ACCOUNT_ID_REQUIRED"
            }

        url = base_url.rstrip("/") + f"/v3/brokerage/accounts/{account_id}/balances"

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
            "balance_attempted": True,
            "http_status": response.status_code,
            "execution_enabled": False,
            "status": "BALANCE_READ_SUCCESS" if response.status_code == 200 else "BALANCE_READ_FAILED",
            "response_preview": response.text[:500],
            "response_json": _safe_json(response)
        }
