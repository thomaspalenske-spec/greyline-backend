"""Execute in the LIQUID part of the session — avoid the wide-spread open and close.

Option spreads are systematically widest in the first minutes after the open (price discovery,
market makers quoting defensively) and the last minutes before the close (inventory unwinding).
The same contract that costs 12% of mid to round-trip at 9:31 can cost 6% at 11:00. Since GreyLine
holds for days, there is no reason to pay the open/close spread tax — it can simply wait for the
liquid window.

This gate applies to NEW ENTRIES, which are never time-critical (a multi-day thesis does not care
about a 20-minute wait). It does NOT gate exits: an urgent exit (a stop, a maturity liquidation)
must fire regardless of spread, and the exit engine already prices those defensively. So the rule
is deliberately asymmetric — patient about getting IN, never about getting OUT when risk says out.

Windows are in Eastern time via MarketHoursEngine (which also handles weekends/holidays).
"""

from datetime import time
from os import getenv

from app.services.market_hours_engine import MarketHoursEngine


class SessionLiquidityWindowEngine:

    # Minutes to avoid after the open and before the close. Override via env for tuning.
    OPEN_SKIP_MIN_DEFAULT = 15
    CLOSE_SKIP_MIN_DEFAULT = 15
    OPEN = time(9, 30)
    CLOSE = time(16, 0)

    @classmethod
    def _skip(cls, name, default):
        try:
            return max(0, int(getenv(name, "") or default))
        except (TypeError, ValueError):
            return default

    def _now_et(self):
        # reuse MarketHoursEngine's tz-aware clock so weekend/holiday logic stays in one place
        import datetime as _dt
        return _dt.datetime.now(MarketHoursEngine.MARKET_TZ)

    def status(self, now_et=None):
        mh = MarketHoursEngine().status()
        now_et = now_et or self._now_et()
        open_skip = self._skip("GREYLINE_LIQUIDITY_OPEN_SKIP_MIN", self.OPEN_SKIP_MIN_DEFAULT)
        close_skip = self._skip("GREYLINE_LIQUIDITY_CLOSE_SKIP_MIN", self.CLOSE_SKIP_MIN_DEFAULT)

        # earliest liquid time = open + open_skip ; latest = close - close_skip
        open_min = self.OPEN.hour * 60 + self.OPEN.minute + open_skip
        close_min = self.CLOSE.hour * 60 + self.CLOSE.minute - close_skip
        t = now_et.time()
        cur_min = t.hour * 60 + t.minute

        in_session = bool(mh.get("is_regular_session"))
        in_liquid = bool(in_session and open_min <= cur_min <= close_min)

        if not in_session:
            reason = "MARKET_NOT_IN_REGULAR_SESSION"
        elif cur_min < open_min:
            reason = f"WITHIN_FIRST_{open_skip}MIN_WIDE_OPENING_SPREADS"
        elif cur_min > close_min:
            reason = f"WITHIN_LAST_{close_skip}MIN_WIDE_CLOSING_SPREADS"
        else:
            reason = "LIQUID_WINDOW"

        return {
            "in_liquid_window": in_liquid,
            "in_regular_session": in_session,
            "reason": reason,
            "market_time": mh.get("market_time"),
            "open_skip_min": open_skip, "close_skip_min": close_skip,
            "status": "SESSION_LIQUIDITY_WINDOW_STATUS",
        }

    def entries_allowed(self, now_et=None):
        """Entries wait for the liquid window; True only inside it."""
        return self.status(now_et)["in_liquid_window"]
