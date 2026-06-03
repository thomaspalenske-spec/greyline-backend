from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def evaluate(self):
        required_keys = [
            "TRADESTATION_API_KEY",
            "TRADESTATION_API_SECRET",
            "TRADESTATION_SANDBOX_URL",
            "TRADESTATION_CALLBACK_URL",
            "TRADESTATION_PAPER_MODE",
        ]

        missing_keys = [
            key for key in required_keys
            if not getenv(key)
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "credentials_loaded": len(missing_keys) == 0,
            "missing_keys": missing_keys,
            "paper_mode": getenv("TRADESTATION_PAPER_MODE", "UNKNOWN"),
            "sandbox_url_present": bool(getenv("TRADESTATION_SANDBOX_URL")),
            "execution_enabled": False,
            "authority_level": "OBSERVE_RECOMMEND_ONLY",
            "status": "READY_FOR_READ_ONLY_PREP" if len(missing_keys) == 0 else "MISSING_CONFIGURATION"
        }
