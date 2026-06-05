from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv, set_key
import requests


class TradeStationTokenExchangeEngine:

    TOKEN_URL = "https://signin.tradestation.com/oauth/token"

    def __init__(self):
        self.env_path = Path(".env")
        load_dotenv(dotenv_path=self.env_path)

    def exchange_code(self):
        payload = {
            "grant_type": "authorization_code",
            "client_id": getenv("TRADESTATION_API_KEY", ""),
            "client_secret": getenv("TRADESTATION_API_SECRET", ""),
            "code": getenv("TRADESTATION_AUTH_CODE", ""),
            "redirect_uri": getenv("TRADESTATION_CALLBACK_URL", ""),
        }

        missing = [key for key, value in payload.items() if not value]

        if missing:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "token_exchange_attempted": False,
                "missing_fields": missing,
                "execution_enabled": False,
                "status": "TOKEN_EXCHANGE_MISSING_FIELDS"
            }

        response = requests.post(
            self.TOKEN_URL,
            data=payload,
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=20
        )

        if response.status_code != 200:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "token_exchange_attempted": True,
                "http_status": response.status_code,
                "response_text": response.text[:500],
                "execution_enabled": False,
                "status": "TOKEN_EXCHANGE_FAILED"
            }

        data = response.json()

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")

        if access_token:
            set_key(str(self.env_path), "TRADESTATION_ACCESS_TOKEN", access_token)

        if refresh_token:
            set_key(str(self.env_path), "TRADESTATION_REFRESH_TOKEN", refresh_token)

        if expires_in:
            set_key(str(self.env_path), "TRADESTATION_TOKEN_EXPIRES_IN", str(expires_in))
            set_key(str(self.env_path), "TRADESTATION_TOKEN_SAVED_AT", datetime.utcnow().isoformat())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "token_exchange_attempted": True,
            "access_token_saved": bool(access_token),
            "refresh_token_saved": bool(refresh_token),
            "expires_in_saved": bool(expires_in),
            "token_saved_at_recorded": bool(expires_in),
            "execution_enabled": False,
            "status": "TOKEN_EXCHANGE_SUCCESS"
        }
