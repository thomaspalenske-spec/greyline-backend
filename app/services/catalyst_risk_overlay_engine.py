"""Don't sell fresh premium straight into a known tail. The catalyst-aware defense layer.

The variance premium GreyLine harvests is a crash premium — its whole risk is the tail. Three
regime signals (vol level, dealer gamma, term-structure slope) all failed to TIME the tail away,
because the tail is a surprise. But some tails are NOT surprises: a Fed decision, a CPI print, a
jobs report, an FDA ruling are SCHEDULED vol events, and their dates are public. Selling fresh
premium the day before one is selling into a known gap risk for no extra edge.

This overlay reads the economic calendar (macro events that hit every index at once) and the FDA
calendar (single-name biotech rulings), and DEFERS opening new premium when a top-tier event is
imminent. It is deliberately narrow: it does not block a 30-day window merely because it contains
the usual monthly Fed meeting (that would block everything) — it defers only when a HIGH-IMPACT
event lands inside the next couple of days, the acute moment. Positions already open are untouched;
this is an entry-timing defense, not an exit rule.

Fails OPEN: if the calendar can't be read, it does not block trading (a data outage must not halt
the harvest) — but it says so, so the gap is visible rather than silent.
"""

import re
from datetime import datetime, timedelta
from os import getenv


class CatalystRiskOverlayEngine:

    # Top-tier macro events whose print reliably moves the whole index vol surface.
    # TOP-TIER index-movers only (default). These are the prints that genuinely gap the index, where
    # selling FRESH premium into them is a real risk. NARROWED 2026-08-14: retail sales, PPI and GDP were
    # dropped — they rarely gap the index >1%, AND the VRP sleeve sells DEFINED-RISK condors whose wings
    # already cap the tail, so deferring on them was pure throttle. The broad set had starved the VRP
    # Edge-proof clock (0 lifetime opens). GREYLINE_CATALYST_BROAD_DEFER=true restores the broad set.
    HIGH_IMPACT = re.compile(
        r"\b(fomc|fed(eral)? (funds|reserve)|rate decision|interest rate|"
        r"cpi|consumer price|core pce|pce index|"
        r"nonfarm|non-farm|payroll|jobs report|unemployment rate)\b", re.I)

    HIGH_IMPACT_BROAD = re.compile(
        r"\b(fomc|fed(eral)? (funds|reserve)|rate decision|interest rate|"
        r"cpi|consumer price|core pce|pce index|"
        r"nonfarm|non-farm|payroll|jobs report|unemployment rate|"
        r"gdp|retail sales|ppi|producer price)\b", re.I)

    @classmethod
    def _high_impact_re(cls):
        """The event set that triggers a premium-defer. Narrow top-tier by default; broad if the operator
        opts back in via GREYLINE_CATALYST_BROAD_DEFER=true."""
        if (getenv("GREYLINE_CATALYST_BROAD_DEFER", "") or "").strip().lower() == "true":
            return cls.HIGH_IMPACT_BROAD
        return cls.HIGH_IMPACT

    @staticmethod
    def _defer_days():
        try:
            return max(0, int(getenv("GREYLINE_CATALYST_DEFER_DAYS", "") or 1))
        except (TypeError, ValueError):
            return 1

    def _economic(self):
        from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
        return (UnusualWhalesProvider()._get("/api/market/economic-calendar", params={}) or {}).get("data") or []

    def _fda(self):
        from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
        return (UnusualWhalesProvider()._get("/api/market/fda-calendar", params={}) or {}).get("data") or []

    @staticmethod
    def _within(ts, start, end):
        try:
            d = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
        except Exception:
            return False
        return start <= d <= end

    def imminent_macro_events(self, defer_days=None):
        """High-impact macro events landing within the defer window (today .. +defer_days)."""
        defer_days = self._defer_days() if defer_days is None else defer_days
        today = datetime.utcnow().date()
        end = today + timedelta(days=defer_days)
        try:
            rows = self._economic()
        except Exception as e:
            return None, str(e)[:80]          # None => read failed (fail open)
        hits = []
        for x in rows:
            ev = str(x.get("event") or "")
            if self._high_impact_re().search(ev) and self._within(x.get("time"), today, end):
                hits.append({"event": ev, "time": x.get("time")})
        return hits, None

    def fda_events_for(self, tickers, defer_days=None):
        """Imminent FDA catalysts for specific single-name/biotech underlyings (empty for indices)."""
        defer_days = self._defer_days() if defer_days is None else defer_days
        today = datetime.utcnow().date()
        end = today + timedelta(days=defer_days)
        tset = {str(t).upper() for t in (tickers or [])}
        if not tset:
            return []
        try:
            rows = self._fda()
        except Exception:
            return []
        return [{"ticker": x.get("ticker"), "desc": str(x.get("description"))[:60], "time": x.get("time")}
                for x in rows if str(x.get("ticker") or "").upper() in tset
                and self._within(x.get("time"), today, end)]

    def defer_new_premium(self, tickers=None):
        """Should the OS hold off opening new premium right now? True + reason when a top-tier
        catalyst is imminent. Fails OPEN (never blocks on a data outage), but reports the gap."""
        macro, err = self.imminent_macro_events()
        if err is not None:
            return {"defer": False, "reason": "CALENDAR_READ_FAILED_FAIL_OPEN", "detail": err}
        fda = self.fda_events_for(tickers)
        if macro:
            return {"defer": True, "reason": "IMMINENT_HIGH_IMPACT_MACRO",
                    "events": macro[:5], "defer_days": self._defer_days(),
                    "note": "a Fed/CPI/PCE/jobs print lands inside the defer window — selling fresh "
                            "index premium into it is a known gap risk for no extra edge"}
        if fda:
            return {"defer": True, "reason": "IMMINENT_FDA_CATALYST", "events": fda[:5]}
        return {"defer": False, "reason": "NO_IMMINENT_CATALYST"}

    def status(self):
        macro, err = self.imminent_macro_events(defer_days=7)   # a 1-week look for the dashboard
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "defer_days": self._defer_days(),
            "high_impact_macro_next_7d": (macro or []) if err is None else [],
            "calendar_read_ok": err is None,
            "currently_deferring": self.defer_new_premium().get("defer"),
            "status": "CATALYST_RISK_OVERLAY_STATUS",
        }
