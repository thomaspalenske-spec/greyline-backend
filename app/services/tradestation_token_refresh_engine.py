import threading
from datetime import datetime
from os import getenv

import requests
from dotenv import set_key
from app.services.env_reload import reload_env
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class TradeStationTokenRefreshEngine:

    # HARD THROTTLE (2026-07-28): TradeStation warned about excessive refresh-token exchanges and can
    # disable the key. This is the SINGLE choke point every refresh path funnels through (maintenance
    # engine, the balance/positions retry services, sim booking), so the cap lives here: at most one
    # token-endpoint call per MIN_REFRESH_INTERVAL_SEC per process. A token refreshed within that
    # window is still valid (>>15 min of its 20 min left), so a skipped refresh is always safe. The
    # lock collapses concurrent callers to a single exchange instead of a burst.
    _lock = threading.Lock()
    _last_attempt_at = None
    MIN_REFRESH_INTERVAL_SEC = 180

    def __init__(self):
        reload_env()

    def refresh(self, force=False):
        now = datetime.utcnow()
        with self._lock:
            if (not force) and self._last_attempt_at is not None and \
                    (now - self._last_attempt_at).total_seconds() < self.MIN_REFRESH_INTERVAL_SEC:
                return {
                    "timestamp": now.isoformat(), "token_refreshed": False,
                    "status": "TOKEN_REFRESH_THROTTLED",
                    "detail": f"a refresh was attempted within {self.MIN_REFRESH_INTERVAL_SEC}s; "
                              "the access token is still valid — reusing it",
                    "execution_enabled": False, "order_placement_allowed": False,
                }
            type(self)._last_attempt_at = now      # claim the slot before releasing the lock

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
