from datetime import datetime
from os import getenv


from app.services.env_reload import reload_env
from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine


class TradeStationTokenMaintenanceEngine:
    """Keep the TradeStation access token fresh — WITHOUT hammering the refresh endpoint.

    TradeStation's access token is valid ~20 min (1200s). They REQUIRE reusing the same access token
    for that full window and only exchanging the refresh token when it is NEAR expiry — refreshing
    eagerly is an abuse pattern they warn (and can disable the key) over. This engine is called at the
    top of many broker calls, so it must be near-free on the common path and refresh at most once per
    token lifetime.

    2026-07-28: fixed a real over-refresh. The buffer was 900s, so a 1200s token was refreshed once it
    was only 300s (5 min) old — ~4x too many refreshes — and the "unknown timestamp" path refreshed
    UNCONDITIONALLY, which a burst of concurrent callers turned into a storm. Now: refresh only in the
    last REFRESH_BUFFER_SEC (default 120s) of the token, plus a hard in-process throttle so no run of
    calls can refresh more than once per MIN_REFRESH_INTERVAL_SEC.
    """

    _last_refresh_at = None                     # in-process, across all instances (shared class state)
    MIN_REFRESH_INTERVAL_SEC = 300              # never refresh more than once per 5 min in this process
    DEFAULT_BUFFER_SEC = 120                    # refresh only in the last 2 min of the ~20 min token

    def __init__(self):
        reload_env()

    def evaluate(self, refresh_buffer_seconds=None):
        if refresh_buffer_seconds is None:
            try:
                refresh_buffer_seconds = int(getenv("GREYLINE_TS_TOKEN_BUFFER_SEC", "") or self.DEFAULT_BUFFER_SEC)
            except Exception:
                refresh_buffer_seconds = self.DEFAULT_BUFFER_SEC

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

        # HARD THROTTLE: never exchange the refresh token more than once per MIN_REFRESH_INTERVAL in
        # this process — a cap against per-call / per-thread storms AND the fail-open path above. A
        # token refreshed within that window still has >= ~15 min of life, so skipping is always safe.
        throttled = False
        if should_refresh and self._last_refresh_at is not None:
            if (datetime.utcnow() - self._last_refresh_at).total_seconds() < self.MIN_REFRESH_INTERVAL_SEC:
                should_refresh = False
                throttled = True
                reason = "REFRESH_THROTTLED_RECENT"

        refresh_result = None
        if should_refresh:
            refresh_result = TradeStationTokenRefreshEngine().refresh()
            type(self)._last_refresh_at = datetime.utcnow()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "TRADESTATION_TOKEN_MAINTENANCE",
            "refresh_buffer_seconds": refresh_buffer_seconds,
            "seconds_until_expiry": seconds_until_expiry,
            "should_refresh": should_refresh,
            "throttled": throttled,
            "maintenance_reason": reason,
            "refresh_attempted": should_refresh,
            "refresh_status": refresh_result.get("status") if refresh_result else None,
            "token_refreshed": refresh_result.get("token_refreshed") if refresh_result else False,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "TRADESTATION_TOKEN_MAINTENANCE_READY",
        }
