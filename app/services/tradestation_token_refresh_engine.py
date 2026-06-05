from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv, set_key
import requests


class TradeStationTokenRefreshEngine:

    TOKEN_URL = "https://signin.tradestation.com/oauth/token"

    def __init__(self):
        self.env_path = Path(".env")
        load_dotenv(dotenv_path=self.env_path)

    def refresh_access_token(self):
        refresh_token = getenv("TRADESTATION_REFRESH_TOKEN", "")
        client_id = getenv("TRADESTATION_API_KEY", "")
        client_secret = getenv("TRADESTATION_API_SECRET", "")

        if not refresh_token or not client_id or not client_secret:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "refresh_attempted": False,
                "execution_enabled": False,
                "status": "REFRESH_TOKEN_OR_CREDENTIALS_REQUIRED"
            }

        response = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=20
        )

        if response.status_code != 200:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "refresh_attempted": True,
                "http_status": response.status_code,
                "response_text": response.text[:500],
                "execution_enabled": False,
                "status": "TOKEN_REFRESH_FAILED"
            }

        data = response.json()

        access_token = data.get("access_token")
        new_refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")

        if access_token:
            set_key(str(self.env_path), "TRADESTATION_ACCESS_TOKEN", access_token)

        if new_refresh_token:
            set_key(str(self.env_path), "TRADESTATION_REFRESH_TOKEN", new_refresh_token)

        if expires_in:
            set_key(str(self.env_path), "TRADESTATION_TOKEN_EXPIRES_IN", str(expires_in))
            set_key(str(self.env_path), "TRADESTATION_TOKEN_SAVED_AT", datetime.utcnow().isoformat())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "refresh_attempted": True,
            "access_token_saved": bool(access_token),
            "refresh_token_saved": bool(new_refresh_token),
            "expires_in_saved": bool(expires_in),
            "token_saved_at_recorded": bool(expires_in),
            "execution_enabled": False,
            "status": "TOKEN_REFRESH_SUCCESS"
        }
