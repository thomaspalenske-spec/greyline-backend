from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv
import requests



def _safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


class TradeStationOrdersLiveEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"), override=True)

    def get_orders(self):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        account_id = getenv("TRADESTATION_MARGIN_ACCOUNT_ID", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://api.tradestation.com")

        if not access_token or not account_id:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "orders_attempted": False,
                "execution_enabled": False,
                "status": "ACCESS_TOKEN_OR_ACCOUNT_ID_REQUIRED"
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
            "status": "ORDERS_READ_SUCCESS" if response.status_code == 200 else "ORDERS_READ_FAILED",
            "response_preview": response.text[:500],
            "response_json": _safe_json(response)
        }
