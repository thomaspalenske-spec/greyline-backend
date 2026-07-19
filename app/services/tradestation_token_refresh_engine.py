from datetime import datetime
from os import getenv

import requests
from dotenv import set_key
from app.services.env_reload import reload_env
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class TradeStationTokenRefreshEngine:

    def __init__(self):
        reload_env()

    def refresh(self):
        api_key = getenv("TRADESTATION_API_KEY", "")
        api_secret = getenv("TRADESTATION_API_SECRET", "")
        refresh_token = getenv("TRADESTATION_REFRESH_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")

        if not api_key or not api_secret or not refresh_token:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "token_refreshed": False,
                "missing_api_key": not bool(api_key),
                "missing_api_secret": not bool(api_secret),
                "missing_refresh_token": not bool(refresh_token),
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "TOKEN_REFRESH_REQUIREMENTS_MISSING",
            }

        url = "https://signin.tradestation.com/oauth/token"

        response = requests.post(
            url,
            data={
                "grant_type": "refresh_token",
                "client_id": api_key,
                "client_secret": api_secret,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )

        try:
            payload = response.json()
        except Exception:
            payload = {}

        if response.status_code != 200 or "access_token" not in payload:
            result = {
                "timestamp": datetime.utcnow().isoformat(),
                "token_refreshed": False,
                "http_status": response.status_code,
                "response_preview": response.text[:500],
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "TOKEN_REFRESH_FAILED",
            }

            ImmutableAuditLedgerEngine().record(
                "TRADESTATION_TOKEN_REFRESH",
                {
                    "token_refreshed": False,
                    "http_status": response.status_code,
                    "status": "TOKEN_REFRESH_FAILED",
                },
            )

            return result

        set_key(".env", "TRADESTATION_ACCESS_TOKEN", payload.get("access_token", ""))

        if payload.get("refresh_token"):
            set_key(".env", "TRADESTATION_REFRESH_TOKEN", payload.get("refresh_token"))

        if payload.get("expires_in"):
            set_key(".env", "TRADESTATION_TOKEN_EXPIRES_IN", str(payload.get("expires_in")))

        set_key(".env", "TRADESTATION_TOKEN_SAVED_AT", datetime.utcnow().isoformat())

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "token_refreshed": True,
            "http_status": response.status_code,
            "expires_in": payload.get("expires_in"),
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "TOKEN_REFRESH_SUCCESS",
        }

        ImmutableAuditLedgerEngine().record(
            "TRADESTATION_TOKEN_REFRESH",
            {
                "token_refreshed": True,
                "http_status": response.status_code,
                "expires_in": payload.get("expires_in"),
                "status": "TOKEN_REFRESH_SUCCESS",
            },
        )

        return result
