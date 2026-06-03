from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationTokenExchangeReadinessEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def evaluate(self):
        required_keys = [
            "TRADESTATION_API_KEY",
            "TRADESTATION_API_SECRET",
            "TRADESTATION_AUTH_CODE",
            "TRADESTATION_CALLBACK_URL",
        ]

        missing_keys = [
            key for key in required_keys
            if not getenv(key)
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "token_exchange_ready": len(missing_keys) == 0,
            "missing_keys": missing_keys,
            "execution_enabled": False,
            "status": "TOKEN_EXCHANGE_READY" if len(missing_keys) == 0 else "TOKEN_EXCHANGE_NOT_READY"
        }
