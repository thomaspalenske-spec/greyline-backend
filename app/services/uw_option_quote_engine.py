"""UW as the SECOND source for a single option's NBBO — the safety net under exit pricing.

The exit engine prices a limit off the contract's live bid/ask. Its primary source is
TradeStation. But when TradeStation's option quote hiccups — missing, stale, one-sided — the
exit engine was forced to fall back to a market order (urgent) or skip entirely (patient). Both
are bad outcomes caused by a *data* gap, not a *decision*.

UW publishes the same NBBO per contract via /api/stock/{ticker}/option-contracts, and it agrees
with TradeStation to the penny on the names we hold (verified 2026-07-24: MRNA 60C both 3.20/4.25).
So UW is the fallback: TradeStation first (real-time, already paid for), UW only when TS fails —
which keeps this off UW's budget in the normal path and only spends it to rescue an exit that
would otherwise mis-execute.

SYMBOL MAP. Internally options are TradeStation-style "MRNA 260828C60". UW is OCC-style
"MRNA260828C00060000" (ticker + YYMMDD + C/P + strike*1000 zero-padded to 8). This engine does
that translation and finds the matching contract in the ticker's chain.
"""

import re
from os import getenv


class UWOptionQuoteEngine:

    # small in-process cache: one option-contracts pull covers a whole (ticker, expiry) chain, so
    # a cycle closing several strikes of the same expiry spends one UW call, not one per strike.
    _cache = {}
    CACHE_TTL_SECONDS = 20

    _SYM = re.compile(r"^([A-Z.]+)\s+(\d{6})([CP])(\d+(?:\.\d+)?)$")

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def parse(cls, ts_symbol):
        """'MRNA 260828C60' -> (ticker, 'YYMMDD', 'C'|'P', strike_float) or None."""
        m = cls._SYM.match(str(ts_symbol or "").upper().strip())
        if not m:
            return None
        return m.group(1), m.group(2), m.group(3), float(m.group(4))

    @staticmethod
    def occ_symbol(ticker, yymmdd, cp, strike):
        """Build the OCC option_symbol UW uses: MRNA260828C00060000."""
        return f"{ticker}{yymmdd}{cp}{int(round(strike * 1000)):08d}"

    @staticmethod
    def _expiry_iso(yymmdd):
        return f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"

    def _chain(self, ticker, expiry_iso, now):
        key = (ticker, expiry_iso)
        hit = self._cache.get(key)
        if hit and (now - hit[0]) <= self.CACHE_TTL_SECONDS:
            return hit[1]
        try:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            r = UnusualWhalesProvider()._get(
                f"/api/stock/{ticker}/option-contracts", params={"expiry": expiry_iso})
            rows = (r or {}).get("data") or []
        except Exception:
            rows = []
        # index by option_symbol for O(1) match
        idx = {str(row.get("option_symbol")): row for row in rows}
        self._cache[key] = (now, idx)
        return idx

    def quote(self, ts_symbol, now=None):
        """(bid, ask) for the contract from UW, or (0.0, 0.0) if unavailable.

        `now` is an injected monotonic time for the cache (tests pass a fixed value; callers pass
        time.monotonic()). Never raises — a failed second source must not break an exit.
        """
        if now is None:
            import time
            now = time.monotonic()
        parsed = self.parse(ts_symbol)
        if not parsed:
            return 0.0, 0.0
        ticker, yymmdd, cp, strike = parsed
        occ = self.occ_symbol(ticker, yymmdd, cp, strike)
        idx = self._chain(ticker, self._expiry_iso(yymmdd), now)
        row = idx.get(occ)
        if not row:
            return 0.0, 0.0
        return self._f(row.get("nbbo_bid")), self._f(row.get("nbbo_ask"))

    @staticmethod
    def enabled():
        # honours the same key the rest of the UW stack uses, resolved via the shared .env/.env.local
        # resolver so the gate can't disagree with the provider; no key -> no fallback, silently
        from app.services.env_reload import uw_api_key
        return bool(uw_api_key())
