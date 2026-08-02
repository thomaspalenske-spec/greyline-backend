"""Forward-track the conditional-VRP candidate — earn the p-value OUT OF SAMPLE.

The backtest said conditional VRP is net-positive after cost but is not statistically significant:
p=0.14 on ~11 monthly units, because one year of data is all UW's vol history provides. You cannot
fix that by re-analysing the same year — more cleverness on the same data is how false discoveries
are manufactured. The only honest way to earn significance is to record the signal LIVE, going
forward, and measure what actually happens on data the hypothesis never saw.

So this panel is to conditional VRP what the earnings-vol panel is to earnings: each day it records
every entry the strategy WOULD take — a rich-IV (causal trailing rank), non-earnings name — capturing
the implied vol and IV rank AT THAT MOMENT (the half that is unrecoverable later). Then, when each
entry's 30-day window completes, it resolves the realized vol (dual-source: UW and TradeStation) and
books the strategy's gross and net edge. The verdict comes only from ACCUMULATED, OUT-OF-SAMPLE
resolutions — nothing here re-uses the backtest year.

It will be slow: entries resolve after ~30 days, so a powered verdict takes months. That is not a
flaw, it is the honest cost of a real out-of-sample test. `panel_status()` says INSUFFICIENT until
it is powered, and never offers a verdict before then.
"""

import json
import math
import statistics
from datetime import datetime
from os import getenv
from pathlib import Path

from app.services.conditional_vrp_research_engine import ConditionalVRPResearchEngine


class ConditionalVRPForwardPanelEngine:

    PANEL = Path("app/data/research/conditional_vrp_forward_panel.jsonl")
    THRESHOLD = 0.67                 # rich-IV = top tercile (the backtest headline threshold)
    IVRANK_LOOKBACK = 252
    COST_LEVELS_BPS = [100, 150, 200]
    REALISTIC_COST_BPS = 150
    MIN_RESOLVED_FOR_VERDICT = 60    # out-of-sample resolutions before any verdict
    PERMUTATIONS = 5000
    SEED = 20260724

    def __init__(self):
        self.cvrp = ConditionalVRPResearchEngine()
        self.vrp = self.cvrp.vrp

    # ------------------------------------------------------------ data (FRESH, not cached)

    def _fresh_series(self, ticker):
        """Pull today's UW vol series directly — the forward panel needs current IV, not the
        research cache (which is frozen for reproducibility)."""
        try:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            r = UnusualWhalesProvider()._get(f"/api/stock/{ticker}/volatility/realized", params={})
            return (r or {}).get("data") or []
        except Exception:
            return []

    def _prefetch_series(self, names, workers=8):
        """Warm the realized-vol series cache for the WHOLE universe CONCURRENTLY so rich_iv_candidates'
        loop hits cache instead of a serial UW call per name — the dominant VRP-cycle cost (~57s for the
        ~200-name universe serially, measured 2026-08-01). Behavior-PRESERVING: identical _fresh_series
        path, only the network fetches overlap; the loop still screens deterministically off the warmed
        provider cache. Each _get builds its own provider/session and the provider cache is lock-guarded,
        so parallel fetches are thread-safe. Best-effort — a failed prefetch just fetches serially below."""
        uniq = list(dict.fromkeys(str(t) for t in (names or []) if t))
        if len(uniq) <= 1:
            return
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(workers, len(uniq))) as ex:
                list(ex.map(self._safe_series, uniq))
        except Exception:
            pass

    def _safe_series(self, ticker):
        try:
            self._fresh_series(ticker)     # populates the provider vol-series cache; result discarded
        except Exception:
            pass

    def _read_panel(self):
        out = []
        try:
            for ln in self.PANEL.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            return []
        return out

    def _append(self, rows):
        if not rows:
            return
        self.PANEL.parent.mkdir(parents=True, exist_ok=True)
        with open(self.PANEL, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    # ------------------------------------------------------------ record side

    def record_signals(self, names=None, save=True):
        """Record every entry the strategy WOULD take today: rich-IV (causal), non-earnings.

        Captures IV + IV rank now (unrecoverable later). Idempotent per (ticker, entry_date).
        """
        names = names or self.vrp.DEFAULT_NAMES
        existing = {(r.get("ticker"), r.get("entry_date")) for r in self._read_panel()}
        today = datetime.utcnow().date().isoformat()
        new = []
        for t in names:
            rows = self._fresh_series(t)
            if len(rows) < 60:
                continue
            rows.sort(key=lambda x: str(x.get("date"))[:10])
            ivs = [self.vrp._f(x.get("implied_volatility")) for x in rows]
            i = len(rows) - 1                                  # today's (latest) observation
            latest = rows[i]
            d = str(latest.get("date"))[:10]
            urv = str(latest.get("unshifted_rv_date"))[:10]    # ~30d forward window end
            iv = ivs[i]
            if iv is None or iv <= 0 or (t, d) in existing:
                continue
            rank = self.cvrp._trailing_rank([v for v in ivs if v is not None], i, self.IVRANK_LOOKBACK)
            if rank is None or rank < self.THRESHOLD:
                continue                                       # not rich enough -> no entry
            earn = self.cvrp._earnings_dates(t)
            if any(d < e <= urv for e in earn):
                continue                                       # earnings in window -> excluded (the tail)
            new.append({
                "kind": "pending", "ticker": t, "entry_date": d, "forward_end": urv,
                "entry_iv": round(iv, 4), "iv_rank": round(rank, 3),
                "entry_spot": self.vrp._f(latest.get("price")),
                "threshold": self.THRESHOLD, "recorded_at": datetime.utcnow().isoformat(),
            })
        if save:
            self._append(new)
        return {"status": "VRP_SIGNALS_RECORDED", "recorded": len(new),
                "as_of": today, "names_scanned": len(names)}

    def rich_iv_candidates(self, names=None):
        """Today's tickers that pass the conditional-VRP signal: rich IV (causal trailing rank
        >= threshold) and NO earnings inside the ~30d window. Shared by the short-premium strategy
        so the traded signal is identical to the one being forward-tracked."""
        names = names or self.vrp.DEFAULT_NAMES
        # PARALLEL PREFETCH the whole universe's vol series so the screen below hits cache instead of a
        # serial UW round-trip per name (measured ~57s serial). The screen stays deterministic.
        self._prefetch_series(names)
        out = []
        for t in names:
            rows = self._fresh_series(t)
            if len(rows) < 60:
                continue
            rows.sort(key=lambda x: str(x.get("date"))[:10])
            ivs = [self.vrp._f(x.get("implied_volatility")) for x in rows]
            i = len(rows) - 1
            latest = rows[i]
            d = str(latest.get("date"))[:10]
            urv = str(latest.get("unshifted_rv_date"))[:10]
            iv = ivs[i]
            if iv is None or iv <= 0:
                continue
            rank = self.cvrp._trailing_rank([v for v in ivs if v is not None], i, self.IVRANK_LOOKBACK)
            if rank is None or rank < self.THRESHOLD:
                continue
            if any(d < e <= urv for e in self.cvrp._earnings_dates(t)):
                continue
            out.append({"ticker": t, "iv": round(iv, 4), "iv_rank": round(rank, 3),
                        "entry_date": d, "forward_end": urv})
        out.sort(key=lambda x: x["iv_rank"], reverse=True)
        return out

    # ------------------------------------------------------------ resolve side

    def resolve(self, save=True):
        """Resolve entries whose 30-day window has completed: forward realized vol (UW + TS),
        gross edge, net across the cost band. One resolution per entry."""
        panel = self._read_panel()
        pending = [r for r in panel if r.get("kind") == "pending"]
        done = {(r.get("ticker"), r.get("entry_date")) for r in panel if r.get("kind") == "resolved"}
        today = datetime.utcnow().date().isoformat()

        rows = []
        for e in pending:
            key = (e["ticker"], e["entry_date"])
            if key in done or str(e.get("forward_end")) >= today:
                continue                                       # window not complete yet
            # UW realized: re-fetch; the entry_date row now carries the completed forward RV
            fresh = self._fresh_series(e["ticker"])
            uw_rv = None
            for x in fresh:
                if str(x.get("date"))[:10] == e["entry_date"]:
                    uw_rv = self.vrp._f(x.get("realized_volatility"))
                    break
            # TS realized: independent, from local price bars over the same window
            ts_map = self.vrp._ts_forward_rv(e["ticker"], asof=today)
            ts_rv = ts_map.get(e["entry_date"])
            if uw_rv is None and ts_rv is None:
                continue
            iv = e["entry_iv"]
            g_uw = self.cvrp._edge_bps(iv, uw_rv) if uw_rv is not None else None
            g_ts = self.cvrp._edge_bps(iv, ts_rv) if ts_rv is not None else None
            gross = g_uw if g_uw is not None else g_ts         # prefer UW, fall back to TS
            rows.append({
                "kind": "resolved", "ticker": e["ticker"], "entry_date": e["entry_date"],
                "month": e["entry_date"][:7], "forward_end": e["forward_end"],
                "entry_iv": iv, "iv_rank": e["iv_rank"],
                "uw_realized": round(uw_rv, 4) if uw_rv is not None else None,
                "ts_realized": round(ts_rv, 4) if ts_rv is not None else None,
                "gross_edge_bps_uw": round(g_uw, 1) if g_uw is not None else None,
                "gross_edge_bps_ts": round(g_ts, 1) if g_ts is not None else None,
                "gross_edge_bps": round(gross, 1) if gross is not None else None,
                "resolved_at": datetime.utcnow().isoformat(),
            })
        if save:
            self._append(rows)
        return {"status": "VRP_PANEL_RESOLVED", "resolved": len(rows),
                "pending_remaining": len(pending) - len(done) - len(rows)}

    # ------------------------------------------------------------ verdict (out-of-sample only)

    def panel_status(self):
        panel = self._read_panel()
        pending = [r for r in panel if r.get("kind") == "pending"]
        resolved = [r for r in panel if r.get("kind") == "resolved" and r.get("gross_edge_bps") is not None]
        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "pending_entries": len(pending),
            "resolved_out_of_sample": len(resolved),
            "threshold_iv_rank": self.THRESHOLD,
            "needed_for_verdict": self.MIN_RESOLVED_FOR_VERDICT,
        }
        if len(resolved) < self.MIN_RESOLVED_FOR_VERDICT:
            out.update({
                "verdict": "INSUFFICIENT_OUT_OF_SAMPLE_DATA",
                "note": ("accrues live; each entry resolves ~30 days after it is recorded. This is "
                         "the honest out-of-sample test the backtest's p=0.14 could not provide — "
                         "it takes months to power, by design"),
            })
            return out

        # monthly cohort inference on OUT-OF-SAMPLE resolutions
        import random
        by_month = {}
        for r in resolved:
            by_month.setdefault(r["month"], []).append(r["gross_edge_bps"])
        monthly = [statistics.mean(v) for _, v in sorted(by_month.items()) if len(v) >= 4]
        if len(monthly) < 4:
            out["verdict"] = "INSUFFICIENT_MONTHS"
            return out
        gross = statistics.mean(monthly)
        sd = statistics.pstdev(monthly) or 1e-9
        rng = random.Random(self.SEED)
        p = self.cvrp._sign_flip_p(monthly, gross, rng, self.PERMUTATIONS)
        net_real = gross - self.REALISTIC_COST_BPS
        worst = min(monthly)
        out.update({
            "gross_edge_bps": round(gross, 1),
            "net_edge_bps_by_cost": {f"{c}bps": round(gross - c, 1) for c in self.COST_LEVELS_BPS},
            "net_edge_at_realistic_cost_bps": round(net_real, 1),
            "break_even_cost_bps": round(gross, 1),
            "sharpe_gross_annualized": round(gross / sd * math.sqrt(12), 2),
            "p_value_out_of_sample": round(p, 4),
            "significant": bool(p < 0.0125),
            "worst_month_bps": round(worst, 1),
            "months": len(monthly),
            "verdict": ("CONFIRMED_OUT_OF_SAMPLE" if (p < 0.0125 and net_real > 0)
                        else "NOT_CONFIRMED_OUT_OF_SAMPLE"),
            "note": "verdict is on OUT-OF-SAMPLE resolutions only — none of the backtest year is reused",
        })
        return out
