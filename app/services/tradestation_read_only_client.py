from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationReadOnlyClient:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def evaluate(self):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        sandbox_url = getenv("TRADESTATION_SANDBOX_URL", "")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "mode": "READ_ONLY",
            "sandbox_url_present": bool(sandbox_url),
            "access_token_present": bool(access_token),
            "execution_enabled": False,
            "supported_read_only_operations": [
                "account_discovery",
                "account_balances",
                "positions",
                "orders"
            ],
            "status": "READY" if access_token and sandbox_url else "TOKEN_REQUIRED"
        }
