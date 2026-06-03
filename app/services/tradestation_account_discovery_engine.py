from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationAccountDiscoveryEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def evaluate(self):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "mode": "READ_ONLY_PREP",
            "access_token_present": bool(access_token),
            "execution_enabled": False,
            "account_discovery_ready": bool(access_token),
            "status": "READY_FOR_ACCOUNT_DISCOVERY" if access_token else "ACCESS_TOKEN_REQUIRED"
        }
