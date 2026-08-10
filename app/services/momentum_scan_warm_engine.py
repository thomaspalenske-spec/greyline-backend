"""Keep the momentum LIVE scan warm so the equity shadow can open weekly cohorts on fresh data.

The momentum-reversal signal needs a scan of the full ~2000-name universe on LIVE bars to pick the top-N.
That scan (produced by /top-candidates's _compute) is a heavy ~5-min TradeStation fetch, so the shadow
deliberately never triggers it inline. This engine runs it ONCE PER TRADING DAY, in the scheduler's
heavy-recompute window (overnight / post-close — the same gate the optionable-universe + condor-shadow
refreshes use), so the top_candidates_cache is always fresh (<26h) and live-sourced when the shadow rolls
into its next weekly cohort. Gated OFF by default (GREYLINE_MOMENTUM_SCAN_WARM) — it adds a recurring
heavy TS fetch, so it's an explicit opt-in. Fail-safe: a bad scan leaves the last good cache untouched.
"""

import json
from datetime import datetime
from os import getenv
from pathlib import Path


class MomentumScanWarmEngine:

    MARKER = Path("app/data/momentum_reversal/scan_warm_last.json")

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_MOMENTUM_SCAN_WARM", "false") or "false").strip().lower() == "true"

    def _last_warm_date(self):
        try:
            return str(json.loads(self.MARKER.read_text()).get("date") or "")
        except Exception:
            return ""

    def _mark(self, et_date, extra):
        try:
            self.MARKER.parent.mkdir(parents=True, exist_ok=True)
            self.MARKER.write_text(json.dumps({"date": et_date, "at": datetime.utcnow().isoformat(), **extra}))
        except Exception:
            pass

    @staticmethod
    def _et_date(market_hours):
        mt = market_hours.get("market_time") if isinstance(market_hours, dict) else None
        if mt:
            return str(mt)[:10]
        return datetime.utcnow().strftime("%Y-%m-%d")   # fail-safe: still bounds to once/day

    def warm_if_due(self, market_hours=None):
        """Run the live universe scan at most once per ET day (the scheduler only calls this in the
        heavy-recompute window, so 'once/day' lands overnight/post-close). Writes the shared scan cache
        that the Opportunity Board AND the momentum shadow both read."""
        if not self.enabled():
            return {"status": "MOM_SCAN_WARM_DISABLED", "ran": False}
        et_date = self._et_date(market_hours or {})
        if self._last_warm_date() == et_date:
            return {"status": "MOM_SCAN_WARM_ALREADY_TODAY", "ran": False, "date": et_date}
        try:
            # reuse the EXACT production compute the /top-candidates route uses, and write the same cache
            from app.routes.top_candidates import _compute, CACHE, BENCH_N
            result = _compute(BENCH_N)
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(result))
        except Exception as exc:
            # leave the last good cache untouched; report degraded so the operator sees the miss
            return {"status": "MOM_SCAN_WARM_DEGRADED", "ran": False, "error": repr(exc)[:160]}
        source = result.get("data_source")
        n = len(result.get("candidates") or [])
        self._mark(et_date, {"source": source, "candidates": n})
        return {"status": "MOM_SCAN_WARM_DONE", "ran": True, "date": et_date,
                "data_source": source, "candidates": n}

    def status(self):
        return {"enabled": self.enabled(), "last_warm": self._last_warm_date(),
                "note": ("once/day live universe scan warms top_candidates_cache for the Opportunity Board "
                         "+ the momentum equity shadow; runs in the scheduler's overnight/post-close window")}
