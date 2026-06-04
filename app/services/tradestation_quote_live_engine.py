from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv
import requests


class TradeStationQuoteLiveEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def get_quote(self, symbol):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://api.tradestation.com")
        symbol = symbol.upper().strip()

        if not access_token or not symbol:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "symbol": symbol,
                "quote_attempted": False,
                "execution_enabled": False,
                "status": "ACCESS_TOKEN_OR_SYMBOL_REQUIRED"
            }

        url = base_url.rstrip("/") + f"/v3/marketdata/quotes/{symbol}"

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
            "symbol": symbol,
            "quote_attempted": True,
            "http_status": response.status_code,
            "execution_enabled": False,
            "status": "QUOTE_READ_SUCCESS" if response.status_code == 200 else "QUOTE_READ_FAILED",
            "response_preview": response.text[:500]
        }
