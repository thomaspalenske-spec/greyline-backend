from datetime import datetime
from os import getenv
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key


class TradeStationAuthCodeExchangeEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"), override=True)

    def exchange(self):
        api_key = getenv("TRADESTATION_API_KEY", "")
        api_secret = getenv("TRADESTATION_API_SECRET", "")
        auth_code = getenv("TRADESTATION_AUTH_CODE", "")
        callback_url = getenv("TRADESTATION_CALLBACK_URL", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://api.tradestation.com")

        if not api_key or not api_secret or not auth_code or not callback_url:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "token_exchanged": False,
                "missing_api_key": not bool(api_key),
                "missing_api_secret": not bool(api_secret),
                "missing_auth_code": not bool(auth_code),
                "missing_callback_url": not bool(callback_url),
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "AUTH_CODE_EXCHANGE_REQUIREMENTS_MISSING",
            }

        url = base_url.rstrip("/") + "/v3/security/authorize/token"

        response = requests.post(
            url,
            data={
                "grant_type": "authorization_code",
                "client_id": api_key,
                "client_secret": api_secret,
                "code": auth_code,
                "redirect_uri": callback_url,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )

        try:
            payload = response.json()
        except Exception:
            payload = {}

        if response.status_code != 200 or "access_token" not in payload:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "token_exchanged": False,
                "http_status": response.status_code,
                "response_preview": response.text[:500],
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "AUTH_CODE_EXCHANGE_FAILED",
            }

        set_key(".env", "TRADESTATION_ACCESS_TOKEN", payload.get("access_token", ""))

        if payload.get("refresh_token"):
            set_key(".env", "TRADESTATION_REFRESH_TOKEN", payload.get("refresh_token"))

        if payload.get("expires_in"):
            set_key(".env", "TRADESTATION_TOKEN_EXPIRES_IN", str(payload.get("expires_in")))

        set_key(".env", "TRADESTATION_TOKEN_SAVED_AT", datetime.utcnow().isoformat())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "token_exchanged": True,
            "http_status": response.status_code,
            "expires_in": payload.get("expires_in"),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "AUTH_CODE_EXCHANGE_SUCCESS",
        }
