from datetime import datetime
import time
from os import getenv
from pathlib import Path
from dotenv import load_dotenv
import requests

from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine


class TradeStationQuoteLiveEngine:
    _quote_cache = {}
    CACHE_TTL_SECONDS = 60

    @classmethod
    def clear_cache(cls):
        cls._quote_cache = {}

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"), override=True)

    def get_quote(self, symbol):
        maintenance = TradeStationTokenMaintenanceEngine().evaluate()
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://api.tradestation.com")
        symbol = symbol.upper().strip()

        if symbol in self._quote_cache:
            cached = dict(self._quote_cache[symbol])

            cache_timestamp = cached.get("_cache_timestamp", 0)
            cache_age_seconds = round(time.time() - cache_timestamp, 2)

            if cache_age_seconds <= self.CACHE_TTL_SECONDS:
                cached["cache_hit"] = True
                cached["cache_age_seconds"] = cache_age_seconds
                return cached

            del self._quote_cache[symbol]

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

        try:
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                },
                timeout=20
            )
        except requests.RequestException as error:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "symbol": symbol,
                "quote_attempted": True,
                "http_status": None,
                "execution_enabled": False,
                "status": "QUOTE_READ_FAILED",
                "error": str(error)
            }

        try:
            response_json = response.json()
        except Exception:
            response_json = None

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "symbol": symbol,
            "quote_attempted": True,
            "http_status": response.status_code,
            "execution_enabled": False,
            "status": "QUOTE_READ_SUCCESS" if response.status_code == 200 else "QUOTE_READ_FAILED",
            "response_json": response_json,
            "response_preview": response.text[:500],
            "cache_hit": False,
        }

        if response.status_code == 200:
            result["_cache_timestamp"] = time.time()
            result["cache_age_seconds"] = 0
            self._quote_cache[symbol] = dict(result)

        return result
