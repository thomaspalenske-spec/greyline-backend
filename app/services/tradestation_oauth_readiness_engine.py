from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationOAuthReadinessEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def evaluate(self):
        api_key = getenv("TRADESTATION_API_KEY")
        api_secret = getenv("TRADESTATION_API_SECRET")
        sandbox_url = getenv("TRADESTATION_SANDBOX_URL")
        callback_url = getenv("TRADESTATION_CALLBACK_URL")

        missing = []

        if not api_key:
            missing.append("TRADESTATION_API_KEY")

        if not api_secret:
            missing.append("TRADESTATION_API_SECRET")

        if not sandbox_url:
            missing.append("TRADESTATION_SANDBOX_URL")

        if not callback_url:
            missing.append("TRADESTATION_CALLBACK_URL")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "oauth_ready": len(missing) == 0,
            "missing_keys": missing,
            "sandbox_url_present": bool(sandbox_url),
            "callback_url_present": bool(callback_url),
            "execution_enabled": False,
            "status": "OAUTH_READY" if len(missing) == 0 else "OAUTH_NOT_READY"
        }
