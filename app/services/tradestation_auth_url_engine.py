from datetime import datetime
from os import getenv
from urllib.parse import urlencode
from app.services.env_reload import reload_env



class TradeStationAuthUrlEngine:

    def __init__(self):
        reload_env()

    def generate(self):
        api_key = getenv("TRADESTATION_API_KEY", "")
        callback_url = getenv("TRADESTATION_CALLBACK_URL", "")

        if not api_key or not callback_url:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "auth_url_ready": False,
                "missing_api_key": not bool(api_key),
                "missing_callback_url": not bool(callback_url),
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "AUTH_URL_REQUIREMENTS_MISSING",
            }

        params = urlencode({
            "response_type": "code",
            "client_id": api_key,
            "redirect_uri": callback_url,
            "audience": "https://api.tradestation.com",
            "scope": "openid profile offline_access MarketData ReadAccount Trade OptionSpreads",
        })

        auth_url = f"https://signin.tradestation.com/authorize?{params}"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "auth_url_ready": True,
            "auth_url": auth_url,
            "callback_url": callback_url,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "TRADESTATION_AUTH_URL_READY",
        }
