from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationIntegrationDashboardEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def get_dashboard(self):
        api_key = getenv("TRADESTATION_API_KEY", "")
        api_secret = getenv("TRADESTATION_API_SECRET", "")
        sandbox_url = getenv("TRADESTATION_SANDBOX_URL", "")
        callback_url = getenv("TRADESTATION_CALLBACK_URL", "")
        paper_mode = getenv("TRADESTATION_PAPER_MODE", "")
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")

        credentials_loaded = bool(api_key and api_secret and sandbox_url and callback_url and paper_mode)
        access_token_present = bool(access_token)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "credentials_loaded": credentials_loaded,
            "oauth_ready": credentials_loaded,
            "access_token_present": access_token_present,
            "read_only_client_ready": bool(sandbox_url),
            "account_discovery_ready": access_token_present,
            "execution_enabled": False,
            "authority_level": "OBSERVE_RECOMMEND_ONLY",
            "status": "READY_FOR_READ_ONLY_CONNECTION" if access_token_present else "ACCESS_TOKEN_REQUIRED"
        }
