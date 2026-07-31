"""The sector map (GreyLine's concentration buckets for the traded universe) — refreshed DAILY, cheaply.

The sector cap can only see a position if its symbol carries a sector; an unmapped name reads as
diversified and the limit stays quiet for the wrong reason. This keeps app/data/sector_map.json current
with the drifting traded universe on the SAME post-close daily gate as the optionable universe.

API-FRUGAL BY DESIGN (operator directive): it does NOT make its own broad sweep. It reads `sector` off
the SAME screener rows the optionable-universe refresh already fetched (OptionableUniverseEngine._fetch,
which caches per cycle) — so the OI ordering costs ZERO extra UW calls — plus ONE marketcap-ordered call
to catch large-caps that aren't OI-liquid. Two engines, effectively one-and-a-bit screener hits a day.

It MERGES (never drops): a name mapped before stays mapped even if a given day's slice omits it, because
sectors are stable and coverage should only grow. STOCKS are data-derived (UW `sector`); ETFs live in
PortfolioExposureEngine's deliberate literal map (UW gives funds no sector) and WIN over this file.
TRADED names still unresolved are recorded so a gap is loud, never silent.
"""

import json
import time
from datetime import datetime
from pathlib import Path

OUT = Path("app/data/sector_map.json")

NORMALISE = {
    "TECHNOLOGY": "TECHNOLOGY", "FINANCIAL_SERVICES": "FINANCIALS", "FINANCIALS": "FINANCIALS",
    "HEALTHCARE": "HEALTHCARE", "CONSUMER_CYCLICAL": "CONSUMER_DISCRETIONARY",
    "CONSUMER_DISCRETIONARY": "CONSUMER_DISCRETIONARY", "CONSUMER_DEFENSIVE": "CONSUMER_STAPLES",
    "CONSUMER_STAPLES": "CONSUMER_STAPLES", "UTILITIES": "UTILITIES", "REAL_ESTATE": "REAL_ESTATE",
    "COMMUNICATION_SERVICES": "COMMUNICATIONS", "COMMUNICATIONS": "COMMUNICATIONS", "ENERGY": "ENERGY",
    "BASIC_MATERIALS": "MATERIALS", "MATERIALS": "MATERIALS", "INDUSTRIALS": "INDUSTRIALS",
}


class SectorMapEngine:

    MIN_ACCEPTABLE = 300          # fewer sectors than this = a failed screen; do NOT persist/clobber

    @staticmethod
    def _norm(value):
        if not value:
            return None
        key = str(value).strip().upper().replace(" ", "_")
        return NORMALISE.get(key, key)

    def _fetch_sectors(self):
        """{ticker: bucket} from the screener rows the optionable engine already fetches. The OI order is
        a cache hit (0 extra calls); 'marketcap' adds ONE call to catch large-caps that aren't OI-liquid."""
        from app.services.optionable_universe_engine import OptionableUniverseEngine
        ou = OptionableUniverseEngine()
        mapping = {}
        for order in ("total_open_interest", "marketcap"):
            for x in ou._fetch(order):
                t = str(x.get("ticker") or "").strip().upper()
                s = self._norm(x.get("sector"))
                if t and s:
                    mapping.setdefault(t, s)
        return mapping

    def _traded_universe(self):
        """The options + ETF-sleeve tradeable set (the momentum SCAN universe is checked separately and
        is NOT the full-market archive). Deterministic — used only to report unresolved holes."""
        traded = set()
        try:
            from app.services.vrp_research_engine import VRPResearchEngine
            traded |= set(VRPResearchEngine.CURATED_FALLBACK)
            from app.services.optionable_universe_engine import OptionableUniverseEngine
            traded |= set(OptionableUniverseEngine().names() or [])
            from app.services.trend_following_engine import TrendFollowingEngine
            from app.services.managed_futures_engine import ManagedFuturesEngine
            traded |= set(TrendFollowingEngine.BASKET) | set(ManagedFuturesEngine.BASKET)
            traded |= {"SGOV", "SVXY", "QQQM", "GLDM"}
        except Exception:
            pass
        return traded

    def regenerate(self, session_date=None):
        fresh = self._fetch_sectors()
        if len(fresh) < self.MIN_ACCEPTABLE:
            return {"status": "SECTOR_MAP_FETCH_FAILED", "mapped": len(fresh), "persisted": False}
        try:
            existing = json.loads(OUT.read_text()).get("sectors") or {}
        except Exception:
            existing = {}
        merged = {**existing, **fresh}                 # MERGE: update/extend, never drop prior coverage
        try:
            from app.services.portfolio_exposure_engine import PortfolioExposureEngine
            lit = PortfolioExposureEngine()
            unresolved = sorted(t for t in self._traded_universe()
                                if t not in merged and lit._sector(t) == "UNKNOWN")
        except Exception:
            unresolved = []
        data = {
            "generated_at": datetime.utcnow().isoformat(), "computed_epoch": time.time(),
            "session_date": session_date, "symbols": len(merged),
            "new_this_run": sorted(set(fresh) - set(existing)), "unresolved": unresolved,
            "sectors": merged, "source": "UNUSUAL_WHALES /screener/stocks (OI reused + marketcap), merged",
        }
        try:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(data, indent=2, sort_keys=True))
            from app.services.portfolio_exposure_engine import PortfolioExposureEngine
            PortfolioExposureEngine._generated_sector_cache = None      # reload the fresh map
        except Exception:
            pass
        return {"status": "SECTOR_MAP_READY", "persisted": True, "symbols": len(merged),
                "unresolved": unresolved, "session_date": session_date}

    def recompute_if_due(self, market_hours=None):
        """Regenerate ONCE PER TRADING DAY at the 16:00 ET close — the SAME gate as the optionable
        universe, so both run in one cycle and share its screener fetch. Bootstraps if missing/thin."""
        from app.services.optionable_universe_engine import OptionableUniverseEngine
        today_et, post_close = OptionableUniverseEngine._session_gate(market_hours)
        try:
            prev = json.loads(OUT.read_text())
            have = len(prev.get("sectors") or {}) >= self.MIN_ACCEPTABLE
        except Exception:
            prev, have = {}, False

        if not have:
            d = self.regenerate(session_date=today_et)
            return {"status": d.get("status"), "ran": True, "trigger": "bootstrap", "symbols": d.get("symbols")}
        if post_close and today_et and prev.get("session_date") != today_et:
            d = self.regenerate(session_date=today_et)
            return {"status": d.get("status"), "ran": True, "trigger": "post_close_refresh",
                    "symbols": d.get("symbols"), "unresolved": d.get("unresolved")}
        return {"status": "SECTOR_MAP_FRESH", "ran": False, "symbols": prev.get("symbols")}
