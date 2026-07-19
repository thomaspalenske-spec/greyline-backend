from datetime import datetime
from os import getenv


from app.services.env_reload import reload_env
from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine


class TradeStationTokenMaintenanceEngine:

    def __init__(self):
        reload_env()

    def evaluate(self, refresh_buffer_seconds=900):
        token_saved_at = getenv("TRADESTATION_TOKEN_SAVED_AT")
        expires_in_raw = getenv("TRADESTATION_TOKEN_EXPIRES_IN")

        try:
            expires_in_seconds = int(expires_in_raw) if expires_in_raw else None
        except Exception:
            expires_in_seconds = None

        seconds_until_expiry = None
        should_refresh = True
        reason = "TOKEN_EXPIRY_UNKNOWN"

        if token_saved_at and expires_in_seconds:
            try:
                saved_at = datetime.fromisoformat(token_saved_at)
                token_age_seconds = int((datetime.utcnow() - saved_at).total_seconds())
                seconds_until_expiry = expires_in_seconds - token_age_seconds

                if seconds_until_expiry > refresh_buffer_seconds:
                    should_refresh = False
                    reason = "TOKEN_STILL_VALID"
                else:
                    should_refresh = True
                    reason = "TOKEN_WITHIN_REFRESH_BUFFER"
            except Exception:
                should_refresh = True
                reason = "TOKEN_TIMESTAMP_PARSE_FAILED"

        refresh_result = None
        if should_refresh:
            refresh_result = TradeStationTokenRefreshEngine().refresh()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "TRADESTATION_TOKEN_MAINTENANCE",
            "refresh_buffer_seconds": refresh_buffer_seconds,
            "seconds_until_expiry": seconds_until_expiry,
            "should_refresh": should_refresh,
            "maintenance_reason": reason,
            "refresh_attempted": should_refresh,
            "refresh_status": refresh_result.get("status") if refresh_result else None,
            "token_refreshed": refresh_result.get("token_refreshed") if refresh_result else False,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "TRADESTATION_TOKEN_MAINTENANCE_READY",
        }
