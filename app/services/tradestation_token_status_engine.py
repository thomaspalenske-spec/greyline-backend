from datetime import datetime, timedelta
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationTokenStatusEngine:
    def __init__(self):
        self.env_path = Path(".env")
        load_dotenv(dotenv_path=self.env_path)

    def evaluate(self):
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        refresh_token = getenv("TRADESTATION_REFRESH_TOKEN", "")
        expires_in_raw = getenv("TRADESTATION_TOKEN_EXPIRES_IN", "")
        saved_at_raw = getenv("TRADESTATION_TOKEN_SAVED_AT", "")

        missing = []

        if not access_token:
            missing.append("TRADESTATION_ACCESS_TOKEN")

        if not refresh_token:
            missing.append("TRADESTATION_REFRESH_TOKEN")

        if not expires_in_raw:
            missing.append("TRADESTATION_TOKEN_EXPIRES_IN")

        if not saved_at_raw:
            missing.append("TRADESTATION_TOKEN_SAVED_AT")

        expires_in_seconds = None
        saved_at = None
        expires_at = None
        seconds_remaining = None
        token_expired = None

        try:
            expires_in_seconds = int(expires_in_raw) if expires_in_raw else None
        except ValueError:
            missing.append("TRADESTATION_TOKEN_EXPIRES_IN_VALID_INTEGER")

        try:
            saved_at = datetime.fromisoformat(saved_at_raw) if saved_at_raw else None
        except ValueError:
            missing.append("TRADESTATION_TOKEN_SAVED_AT_VALID_ISOFORMAT")

        if expires_in_seconds is not None and saved_at is not None:
            expires_at = saved_at + timedelta(seconds=expires_in_seconds)
            seconds_remaining = int((expires_at - datetime.utcnow()).total_seconds())
            token_expired = seconds_remaining <= 0

        ready_for_read_only = (
            bool(access_token)
            and bool(refresh_token)
            and expires_in_seconds is not None
            and saved_at is not None
            and token_expired is False
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "access_token_present": bool(access_token),
            "refresh_token_present": bool(refresh_token),
            "expires_in_present": bool(expires_in_raw),
            "token_saved_at_present": bool(saved_at_raw),
            "expires_in_seconds": expires_in_seconds,
            "token_saved_at": saved_at_raw or None,
            "token_expires_at": expires_at.isoformat() if expires_at else None,
            "seconds_remaining": seconds_remaining,
            "token_expired": token_expired,
            "ready_for_read_only": ready_for_read_only,
            "execution_enabled": False,
            "missing_fields": missing,
            "status": "TOKEN_READY_FOR_READ_ONLY" if ready_for_read_only else "TOKEN_NOT_READY"
        }
