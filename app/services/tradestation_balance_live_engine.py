from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv
import requests


class TradeStationBalanceLiveEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def get_balance(self):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        account_id = getenv("TRADESTATION_MARGIN_ACCOUNT_ID", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://api.tradestation.com")

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
            "response_preview": response.text[:500]
        }
