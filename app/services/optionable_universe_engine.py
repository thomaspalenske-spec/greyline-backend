"""The VRP / options universe, DERIVED from live option-liquidity data — not a hand-typed list.

WHY THIS EXISTS: the short-premium (condor) sleeves need a candidate universe of names that are
genuinely tradeable as defined-risk iron condors. That is a *present-day liquidity* question — deep,
tight-spread option chains with a real IV surface — and the honest way to answer it is to screen the
market on today's option liquidity, not to maintain a static list somebody typed by hand (which drifts,
embeds selection bias, and never notices when a name gains or loses an options market).

This is deliberately the OPPOSITE mandate from UniverseExpansionEngine (the equity universe), which
must NOT screen on present-day liquidity because it builds 25 years of point-in-time history and that
would be look-ahead. Here there is no history and no look-ahead: we are choosing what to SELL TODAY, so
screening on today's option open interest is exactly correct. Two engines, two mandates, no overlap.

SOURCE: UW /api/screener/stocks returns, per name, total_open_interest + avg_30_day_call/put_oi +
avg_30_day_call/put_volume (true option liquidity), plus marketcap, sector, is_index, issue_type and
the IV surface (iv30d, iv_rank, variance_risk_premium). Ordering by total_open_interest desc puts the
deeply-optionable names (SPY/QQQ/NVDA/TLT/IWM/...) at the top in a single call.

STABILITY: the traded universe must be identical to the one the forward-test tracks, so it refreshes
SLOWLY (monthly TTL) rather than churning daily. FAIL-SAFE: if the screen ever fails or returns an
implausibly small set, names() returns None and callers fall back to the curated list — the universe
can never silently empty.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

CACHE = Path("app/data/research/optionable_universe.json")
SCREENER = "https://api.unusualwhales.com/api/screener/stocks"


class OptionableUniverseEngine:

    PAGE = 500                        # UW screener hard cap per request (top-N by the chosen order)
    ALLOWED_TYPES = {"Common Stock", "ETF"}   # cash-settled indices / ADRs / units excluded by default

    # Rule parameters (env-overridable) — the screen, expressed as data thresholds instead of a typist.
    DEFAULT_MIN_OI = 250_000          # total option open interest floor = a real, deep options market
    # Common-stock cap floor (ETFs exempt — AUM ≠ marketcap). $10B is the large-cap line that keeps the
    # deeply-optionable names while excluding the small-cap, high-retail-OI lottery tickets (AMC/BB/etc)
    # whose options are rich for a REASON — binary/meme gap risk a defined-risk condor can't survive.
    DEFAULT_MIN_MARKETCAP = 10.0e9
    DEFAULT_TARGET_SIZE = 250         # keep the richest-liquidity N (matches the ~200-name sweet spot)
    POST_CLOSE_ET_MIN = 16 * 60       # refresh at/after 16:00 ET — settled data, once per trading day
    MIN_ACCEPTABLE = 50               # fewer than this = a failed screen; do NOT trust / do NOT persist

    # ---- knobs -------------------------------------------------------------------------------------
    @property
    def min_oi(self):
        return self._envf("GREYLINE_OPTIONABLE_MIN_OI", self.DEFAULT_MIN_OI)

    @property
    def min_marketcap(self):
        return self._envf("GREYLINE_OPTIONABLE_MIN_MARKETCAP", self.DEFAULT_MIN_MARKETCAP)

    @property
    def target_size(self):
        return int(self._envf("GREYLINE_OPTIONABLE_TARGET_SIZE", self.DEFAULT_TARGET_SIZE))

    @staticmethod
    def _envf(name, default):
        try:
            v = os.getenv(name)
            return float(v) if v is not None and v != "" else float(default)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _headers(self):
        return {"Authorization": f"Bearer {os.getenv('UNUSUAL_WHALES_API_KEY')}",
                "Accept": "application/json"}

    # ---- live fetch (isolated so tests can monkeypatch it) -----------------------------------------
    _fetch_cache = {}          # {order: (epoch, rows)} — shared so co-scheduled consumers reuse one call
    _FETCH_TTL_S = 900         # a cycle's worth: the SectorMapEngine piggybacks on this same fetch

    def _fetch(self, order="total_open_interest"):
        """Top PAGE names by `order`, richest first. Returns the raw screener rows (or []).

        Cached briefly so a second consumer in the same scheduler cycle (the sector map, which reads
        `sector` off these SAME rows) does NOT spend another UW call — one screener hit feeds both."""
        hit = OptionableUniverseEngine._fetch_cache.get(order)
        if hit and (time.time() - hit[0]) < self._FETCH_TTL_S:
            return hit[1]
        try:
            r = requests.get(SCREENER,
                             params={"limit": self.PAGE, "order": order, "order_direction": "desc"},
                             headers=self._headers(), timeout=60)
            rows = ((r.json() or {}).get("data") or []) if r.status_code == 200 else []
        except Exception:
            rows = []
        if rows:
            OptionableUniverseEngine._fetch_cache[order] = (time.time(), rows)
        return rows

    # ---- the screen --------------------------------------------------------------------------------
    def screen(self):
        """Apply the option-liquidity rule to the live screener and return the ranked membership."""
        rows = self._fetch("total_open_interest")
        min_oi, min_cap = self.min_oi, self.min_marketcap
        kept = []
        for x in rows:
            t = (x.get("ticker") or "").strip().upper()
            if not t or not t.isalnum():                       # drop blanks and odd symbols (SPXW etc.)
                continue
            if x.get("is_index"):                              # cash-settled index products — not our framework
                continue
            itype = x.get("issue_type") or ""
            if itype not in self.ALLOWED_TYPES:
                continue
            oi = self._f(x.get("total_open_interest")) or 0
            if oi < min_oi:                                    # no deep options market → not condor-able
                continue
            iv = self._f(x.get("iv30d")) or 0
            if iv <= 0:                                         # no live IV surface → no VRP signal to trade
                continue
            cap = self._f(x.get("marketcap")) or 0
            if itype == "Common Stock" and cap < min_cap:      # ETFs exempt (AUM ≠ marketcap)
                continue
            kept.append({
                "ticker": t, "total_open_interest": int(oi),
                "option_volume_30d": int((self._f(x.get("avg_30_day_call_volume")) or 0)
                                         + (self._f(x.get("avg_30_day_put_volume")) or 0)),
                "marketcap": cap, "sector": x.get("sector"), "issue_type": itype,
                "iv30d": round(iv, 4), "iv_rank": self._f(x.get("iv_rank")),
                "variance_risk_premium": self._f(x.get("variance_risk_premium")),
            })
        kept.sort(key=lambda r: r["total_open_interest"], reverse=True)
        return kept[: self.target_size]

    # ---- compute + persist (scheduler) -------------------------------------------------------------
    def recompute(self, session_date=None):
        rows = self.screen()
        if len(rows) < self.MIN_ACCEPTABLE:
            # A failed / implausibly thin screen must NOT clobber a good cache or empty the universe.
            return {"status": "OPTIONABLE_UNIVERSE_SCREEN_FAILED", "kept": len(rows), "persisted": False}
        data = {
            "timestamp": datetime.utcnow().isoformat(), "computed_epoch": time.time(),
            "session_date": session_date,        # the ET trading day this screen represents (once/day gate)
            "count": len(rows), "tickers": [r["ticker"] for r in rows], "rows": rows,
            "source": "UNUSUAL_WHALES /screener/stocks (order=total_open_interest)",
            "rule": {"min_total_open_interest": self.min_oi, "min_marketcap_common": self.min_marketcap,
                     "allowed_types": sorted(self.ALLOWED_TYPES), "exclude_index": True,
                     "target_size": self.target_size, "refresh": "daily at market close (>=16:00 ET)"},
            "status": "OPTIONABLE_UNIVERSE_READY",
        }
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(data))
        except Exception:
            pass
        return {**data, "persisted": True}

    @classmethod
    def _session_gate(cls, market_hours):
        """(today_ET_iso, is_post_close) from the scheduler's market_hours — trading days only."""
        if not market_hours:
            return None, False
        if str(market_hours.get("is_weekday")) != "True" or str(market_hours.get("is_holiday")) == "True":
            return None, False
        try:
            et = datetime.fromisoformat(str(market_hours.get("market_time")))
        except Exception:
            return None, False
        return et.date().isoformat(), (et.hour * 60 + et.minute) >= cls.POST_CLOSE_ET_MIN

    def recompute_if_due(self, market_hours=None):
        """Scheduler entry: re-screen ONCE PER TRADING DAY, at/after the 16:00 ET close (settled data).

        Also bootstraps immediately if there is no usable cache yet, so a fresh deploy is never left
        without a universe until the next close. Fail-safe: a broken screen keeps the last good cache."""
        today_et, post_close = self._session_gate(market_hours)
        try:
            prev = json.loads(CACHE.read_text())
            have_cache = len(prev.get("tickers") or []) >= self.MIN_ACCEPTABLE
        except Exception:
            prev, have_cache = {}, False

        if not have_cache:                                   # bootstrap — screen now, whatever the time
            d = self.recompute(session_date=today_et)
            return {"status": d.get("status"), "ran": True, "trigger": "bootstrap",
                    "count": d.get("count"), "persisted": d.get("persisted")}

        if post_close and today_et and prev.get("session_date") != today_et:
            d = self.recompute(session_date=today_et)        # the daily close refresh
            return {"status": d.get("status"), "ran": True, "trigger": "post_close_refresh",
                    "count": d.get("count"), "persisted": d.get("persisted")}

        return {"status": "OPTIONABLE_UNIVERSE_FRESH", "ran": False, "count": prev.get("count"),
                "session_date": prev.get("session_date")}

    # ---- read (VRP resolver + route) ---------------------------------------------------------------
    def names(self):
        """The derived universe tickers, or None if unavailable — callers fall back to the curated list."""
        try:
            d = json.loads(CACHE.read_text())
            tickers = d.get("tickers") or []
            return tickers if len(tickers) >= self.MIN_ACCEPTABLE else None
        except Exception:
            return None

    def report(self, limit=300):
        try:
            d = json.loads(CACHE.read_text())
            age = round(time.time() - float(d.get("computed_epoch") or 0))
            return {**d, "rows": (d.get("rows") or [])[:limit], "cache_age_seconds": age,
                    "cache_age_days": round(age / 86400, 1)}
        except Exception:
            return {"status": "OPTIONABLE_UNIVERSE_WARMING", "count": 0, "tickers": [], "rows": [],
                    "note": "no derived universe cached yet — the scheduler will screen it, "
                            "and the VRP sleeve falls back to the curated list until then"}
