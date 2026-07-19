from datetime import datetime
from os import getenv
import requests
from app.services.env_reload import reload_env



def _safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


class TradeStationAccountDiscoveryLiveEngine:

    def __init__(self):
        reload_env()

    def discover_accounts(self):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")

        if not access_token:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "account_discovery_attempted": False,
                "execution_enabled": False,
                "status": "ACCESS_TOKEN_REQUIRED"
            }

        url = base_url.rstrip("/") + "/v3/brokerage/accounts"

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
            "account_discovery_attempted": True,
            "http_status": response.status_code,
            "execution_enabled": False,
            "status": "ACCOUNT_DISCOVERY_SUCCESS" if response.status_code == 200 else "ACCOUNT_DISCOVERY_FAILED",
            "response_preview": response.text[:500],
            "response_json": _safe_json(response)
        }
