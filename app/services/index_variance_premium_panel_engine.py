"""Forward-track THE candidate — the index variance risk premium — out of sample.

The dispersion study found the one edge that cleared significance: the variance premium is
concentrated in broad-index ETFs (SPY/RSP/XLF/... VRP 13-20% of IV), not single names. The daily
block bootstrap made it robust (CI [+1.48,+3.66] vol pts, t~5.2) — but ON A SINGLE YEAR that almost
certainly contains no major crash, so the backtest structurally understates the left tail. The
only test that can ever include a real crash regime is a forward, out-of-sample one.

The general forward panel records all 201 names, diluting the index signal with single names whose
VRP is ~0. This panel records ONLY the confirmed index harvest set, so the out-of-sample scoreboard
measures the ACTUAL thesis: does the broad-index variance premium stay positive after cost, and
what does its tail look like when a live crash regime finally shows up?

Same discipline as the other panels: capture IV + IV rank NOW (unrecoverable later), resolve the
forward-aligned realized vol (dual-source UW + TradeStation) once the ~30d window closes, and offer
no verdict until powered — with an autocorrelation-robust block-bootstrap CI once enough resolve.
"""

import json
import math
import random
import statistics
from datetime import datetime
from pathlib import Path

from app.services.conditional_vrp_short_premium_engine import VARIANCE_HARVEST as INDEX_ETFS
from app.services.conditional_vrp_research_engine import ConditionalVRPResearchEngine


class IndexVariancePremiumPanelEngine:

    PANEL = Path("app/data/research/index_variance_premium_panel.jsonl")
    IVRANK_LOOKBACK = 252
    MIN_RESOLVED_FOR_VERDICT = 40    # index basket -> ~15 names/day, so this accrues faster
    BOOTSTRAP_BLOCK = 21
    SEED = 20260724

    def __init__(self):
        self.cvrp = ConditionalVRPResearchEngine()
        self.vrp = self.cvrp.vrp

    # ------------------------------------------------------------ data

    def _fresh_series(self, ticker):
        try:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            r = UnusualWhalesProvider()._get(f"/api/stock/{ticker}/volatility/realized", params={})
            return (r or {}).get("data") or []
        except Exception:
            return []

    def _read(self):
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

    # ------------------------------------------------------------ record

    def record(self, save=True):
        """Record today's index-ETF entries: IV + causal IV rank, one per (ticker, date).

        Unlike the conditional panel this records EVERY index ETF (no rich-IV gate) — the thesis
        is the UNCONDITIONAL index premium; iv_rank is tagged so the rich-IV timing view is still
        available at analysis. ETFs have no earnings, so no earnings exclusion is needed."""
        existing = {(r.get("ticker"), r.get("entry_date")) for r in self._read()}
        new = []
        for t in INDEX_ETFS:
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
            if iv is None or iv <= 0 or (t, d) in existing:
                continue
            rank = self.cvrp._trailing_rank([v for v in ivs if v is not None], i, self.IVRANK_LOOKBACK)
            new.append({
                "kind": "pending", "ticker": t, "entry_date": d, "forward_end": urv,
                "entry_iv": round(iv, 4), "iv_rank": round(rank, 3) if rank is not None else None,
                "recorded_at": datetime.utcnow().isoformat(),
            })
        if save:
            self._append(new)
        return {"status": "INDEX_VRP_RECORDED", "recorded": len(new), "universe": len(INDEX_ETFS)}

    # ------------------------------------------------------------ resolve

    def resolve(self, save=True):
        panel = self._read()
        pending = [r for r in panel if r.get("kind") == "pending"]
        done = {(r.get("ticker"), r.get("entry_date")) for r in panel if r.get("kind") == "resolved"}
        today = datetime.utcnow().date().isoformat()
        rows = []
        for e in pending:
            key = (e["ticker"], e["entry_date"])
            if key in done or str(e.get("forward_end")) >= today:
                continue
            fresh = self._fresh_series(e["ticker"])
            uw_rv = None
            for x in fresh:
                if str(x.get("date"))[:10] == e["entry_date"]:
                    uw_rv = self.vrp._f(x.get("realized_volatility"))
                    break
            ts_rv = self.vrp._ts_forward_rv(e["ticker"], asof=today).get(e["entry_date"])
            rv = uw_rv if uw_rv is not None else ts_rv
            if rv is None:
                continue
            iv = e["entry_iv"]
            rows.append({
                "kind": "resolved", "ticker": e["ticker"], "entry_date": e["entry_date"],
                "month": e["entry_date"][:7], "entry_iv": iv, "iv_rank": e.get("iv_rank"),
                "uw_realized": round(uw_rv, 4) if uw_rv is not None else None,
                "ts_realized": round(ts_rv, 4) if ts_rv is not None else None,
                "vrp": round(iv - rv, 4), "vrp_pct_of_iv": round((iv - rv) / iv * 100, 1) if iv else None,
                "resolved_at": datetime.utcnow().isoformat(),
            })
        if save:
            self._append(rows)
        return {"status": "INDEX_VRP_RESOLVED", "resolved": len(rows)}

    # ------------------------------------------------------------ verdict

    def _block_bootstrap_ci(self, series):
        n = len(series)
        if n < 40:
            return None
        rng = random.Random(self.SEED)
        L = min(self.BOOTSTRAP_BLOCK, max(2, n // 4))
        boot = []
        for _ in range(4000):
            s = []
            while len(s) < n:
                st = rng.randint(0, n - L)
                s.extend(series[st:st + L])
            boot.append(statistics.mean(s[:n]))
        boot.sort()
        return round(boot[100], 4), round(boot[-100], 4), sum(1 for b in boot if b <= 0) / len(boot)

    def status(self):
        panel = self._read()
        pending = [r for r in panel if r.get("kind") == "pending"]
        resolved = [r for r in panel if r.get("kind") == "resolved" and r.get("vrp") is not None]
        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "harvest_universe": INDEX_ETFS,
            "pending_entries": len(pending),
            "resolved_out_of_sample": len(resolved),
            "needed_for_verdict": self.MIN_RESOLVED_FOR_VERDICT,
        }
        if len(resolved) < self.MIN_RESOLVED_FOR_VERDICT:
            out.update({"verdict": "INSUFFICIENT_OUT_OF_SAMPLE_DATA",
                        "note": ("accrues live; ~15 index names/day, resolves ~30d out. This is the "
                                 "ONLY test that can include a real crash regime — the backtest "
                                 "could not. No verdict until powered.")})
            return out
        vrps = [r["vrp"] for r in resolved]
        mean = statistics.mean(vrps)
        ci = self._block_bootstrap_ci(vrps)
        rich = [r["vrp"] for r in resolved if (r.get("iv_rank") or 0) >= 0.67]
        out.update({
            "mean_vrp_vol_points": round(mean, 4),
            "pct_positive": round(sum(1 for x in vrps if x > 0) / len(vrps), 3),
            "worst_vrp": round(min(vrps), 4),
            "rich_iv_mean_vrp": round(statistics.mean(rich), 4) if rich else None,
            "block_bootstrap_95ci": {"lo": ci[0], "hi": ci[1], "p_le_0": ci[2]} if ci else None,
            "verdict": ("INDEX_VRP_CONFIRMED_OOS" if (ci and ci[0] > 0)
                        else "INDEX_VRP_NOT_CONFIRMED_OOS"),
            "note": ("out-of-sample only; CI is block-bootstrap (autocorrelation-robust). A positive "
                     "mean here still carries the crash tail the sample may not yet contain."),
        })
        return out
