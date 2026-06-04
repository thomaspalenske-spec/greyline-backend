from datetime import datetime
from os import getenv
from pathlib import Path
from urllib.parse import urlencode
from dotenv import load_dotenv


class TradeStationOAuthUrlEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def generate_url(self):
        client_id = getenv("TRADESTATION_API_KEY", "")
        redirect_uri = getenv("TRADESTATION_CALLBACK_URL", "")

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "audience": "https://api.tradestation.com",
            "state": "greyline_read_only",
            "scope": "openid offline_access ReadAccount MarketData"
        }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "auth_url": "https://signin.tradestation.com/authorize?" + urlencode(params),
            "execution_enabled": False,
            "status": "OAUTH_URL_READY" if client_id and redirect_uri else "OAUTH_URL_MISSING_CONFIG"
        }
