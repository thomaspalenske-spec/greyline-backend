"""Overnight-return anomaly — a ZERO-CAPITAL forward-test shadow.

THE EDGE (documented across quant finance, Cooper-Cliff-Gulen et al.): nearly all of equity's risk premium
historically accrues OVERNIGHT (close -> next open), while the intraday session (open -> close) is roughly
flat-to-negative. A strategy that holds the market ONLY overnight and stays flat intraday would capture it.

WHY IT'S THE RIGHT NEXT TEST (elite-OS survey, 2026-08-19): it is orthogonal to GreyLine's one confirmed
edge (the VRP vol premium) — an equity TIMING effect, not a vol premium — so it diversifies the edge base
instead of doubling down on short vol; and it trades as CHEAP EQUITY (hold overnight, flat intraday), so it
sidesteps the option round-trip cost that killed every directional edge GreyLine tested.

THE SHADOW: each trading day it records the equal-weight OVERNIGHT return of a LIQUID universe
(open_t / close_{t-1} - 1), cost-nets the close<->open spread you actually cross to capture it, and accrues
one independent daily observation. Judged on the edge court's RIGOROUS bar (verdict_from_returns: cost-net,
95% CI, min-N gate). NO orders — forward-only from deploy. An in-sample historical_context is shown for
immediate insight but is NOT the verdict (survivor-only universe biases it UPWARD; only the forward series
earns a verdict).

HONEST CAVEAT the test must survive: the overnight premium has WEAKENED (and flipped for some assets) since
~2015, and the close<->open spread is the killer on a small edge — which is exactly why it is cost-netted
and swept, and why the liquid, tight-spread universe is used first."""

import csv
from datetime import datetime
from os import getenv
from pathlib import Path

from app.services.persistence.json_store import append_jsonl, read_jsonl

STATE = Path("app/data/overnight_shadow")
BARS = Path("app/data/historical")


class OvernightAnomalyShadowEngine:

    LEDGER = STATE / "overnight_returns.jsonl"
    MIN_DAYS = 20                       # court gate: ~20 independent trading days before any verdict
    COST_GRID_BPS = [0, 1, 2, 4, 6, 10, 15]   # round-trip close<->open cost sweep

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_OVERNIGHT_SHADOW", "true") or "true").strip().lower() == "true"

    # The overnight premium is REAL gross (Sharpe ~0.9 over 28y) but breaks even at only ~3.7bps round-trip,
    # so it's tradeable ONLY in the very tightest-spread instruments. The universe is therefore the broad-index
    # MEGA-ETFs (~1-2bps close<->open), not the wider sector-ETF basket where the cost eats it.
    MEGA_ETFS = ["SPY", "QQQ", "IWM", "DIA"]

    @classmethod
    def _round_trip_cost(cls):
        """Round-trip close<->open spread crossed to capture the overnight return. Default 3bps — a
        conservative estimate for the mega-ETF universe (real is ~1-2bps); env-tunable and swept in the report."""
        try:
            return max(0.0, float(getenv("GREYLINE_OVERNIGHT_COST_BPS", "3"))) / 10000.0
        except (TypeError, ValueError):
            return 0.0003

    @classmethod
    def _universe(cls):
        """The tightest-spread, always-tradeable broad-index ETFs — the ONLY place the cost-fragile overnight
        premium plausibly survives net of the close<->open spread. Wider sector ETFs / single names would be
        eaten by cost (see the report's cost_sweep). Override with GREYLINE_OVERNIGHT_UNIVERSE (comma-sep)."""
        raw = (getenv("GREYLINE_OVERNIGHT_UNIVERSE", "") or "").strip()
        if raw:
            return [s.strip().upper() for s in raw.split(",") if s.strip()]
        return list(cls.MEGA_ETFS)

    @staticmethod
    def _open_close(sym):
        """Sorted [(date, open, close)] for `sym` from the daily bars; skips any bar with a non-positive
        open/close so a bad print can't poison the overnight ratio."""
        rows = []
        try:
            with open(BARS / f"{sym}_daily.csv") as f:
                for r in csv.DictReader(f):
                    try:
                        o, c = float(r["open"]), float(r["close"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if o > 0 and c > 0:
                        rows.append((str(r["date"])[:10], o, c))
        except Exception:
            return []
        rows.sort()
        return rows

    @classmethod
    def _overnight_by_date(cls, syms):
        """{date: equal-weight overnight return} across `syms`. Overnight return for day t = open_t /
        close_{t-1} - 1 (a name contributes to date t only if it has both bars)."""
        from collections import defaultdict
        agg = defaultdict(lambda: [0.0, 0])
        for s in syms:
            oc = cls._open_close(s)
            for i in range(1, len(oc)):
                prev_close = oc[i - 1][2]
                open_t = oc[i][1]
                if prev_close > 0:
                    agg[oc[i][0]][0] += open_t / prev_close - 1.0
                    agg[oc[i][0]][1] += 1
        return {d: sm / n for d, (sm, n) in agg.items() if n > 0}

    # ---- forward accrual (scheduler) ------------------------------------------------------------
    def run_if_due(self):
        """Append the most recent not-yet-recorded overnight observation. Forward-only, once/day, real
        trading days only (the bar dates ARE trading days). No orders. Best-effort."""
        if not self.enabled():
            return {"status": "OVERNIGHT_SHADOW_DISABLED", "ran": False}
        by_date = self._overnight_by_date(self._universe())
        if not by_date:
            return {"status": "OVERNIGHT_SHADOW_NO_DATA", "ran": False}
        led = read_jsonl(self.LEDGER) or []
        # FORWARD-ONLY: on first deploy record ONLY the latest observation (the start point) — never backfill
        # the decades of history (that would be an in-sample backtest, not a forward test). Thereafter accrue
        # every date AFTER the last recorded one (fills a short gap if the service was down, still all post-deploy).
        if not led:
            new = [max(by_date)]
        else:
            last = max(str(r.get("date")) for r in led)
            new = sorted(d for d in by_date if d > last)
        for d in new:
            append_jsonl(self.LEDGER, {"date": d, "gross_overnight_ret": round(by_date[d], 6),
                                       "recorded_at": datetime.utcnow().isoformat()})
        return {"status": "OVERNIGHT_SHADOW_RAN", "ran": True, "observations_added": len(new),
                "total_observations": len(led) + len(new)}

    # ---- report / verdict -----------------------------------------------------------------------
    @staticmethod
    def _stats(rets):
        import math
        n = len(rets)
        if n < 2:
            return None
        mean = sum(rets) / n
        var = sum((r - mean) ** 2 for r in rets) / (n - 1)
        sd = math.sqrt(var)
        ann = (1 + mean) ** 252 - 1 if mean > -1 else -1.0
        sharpe = (mean / sd) * math.sqrt(252) if sd > 1e-12 else None
        return {"n": n, "mean_bps_per_day": round(mean * 10000, 3), "annualized_pct": round(ann * 100, 2),
                "sharpe_annualized": round(sharpe, 2) if sharpe is not None else None,
                "hit_rate": round(sum(1 for r in rets if r > 0) / n, 3)}

    def _cost_sweep(self, gross):
        out = []
        for bps in self.COST_GRID_BPS:
            c = bps / 10000.0
            net = [g - c for g in gross]
            m = sum(net) / len(net) if net else 0.0
            out.append({"cost_bps": bps, "net_mean_bps_per_day": round(m * 10000, 3),
                        "net_annualized_pct": round(((1 + m) ** 252 - 1) * 100, 2) if m > -1 else None})
        return out

    def report(self):
        from app.services.edge_persistence_engine import EdgePersistenceEngine as EP
        syms = self._universe()
        cost = self._round_trip_cost()

        # forward shadow — the RIGOROUS verdict, out-of-sample from deploy
        led = read_jsonl(self.LEDGER) or []
        fwd_gross = [float(r.get("gross_overnight_ret") or 0.0) for r in led]
        fwd_net = [g - cost for g in fwd_gross]
        verdict = EP.verdict_from_returns(fwd_net, min_n=self.MIN_DAYS)
        verdict.update({"track": "FORWARD_SHADOW (out-of-sample, zero-capital) — the verdict",
                        "cost_bps_assumed": round(cost * 10000, 1),
                        "first_obs": led[0].get("date") if led else None,
                        "last_obs": led[-1].get("date") if led else None})

        # historical context — in-sample, survivor-biased; for immediate insight, NOT a verdict
        by_date = self._overnight_by_date(syms)
        hist_gross = [by_date[d] for d in sorted(by_date)]
        hist_net = [g - cost for g in hist_gross]
        return {
            "as_of": datetime.utcnow().isoformat(),
            "universe": {"kind": "liquid_etfs", "n_names": len(syms), "names": syms},
            "cost_assumption_bps": round(cost * 10000, 1),
            "forward_shadow": verdict,
            "historical_context": {
                "label": ("IN-SAMPLE BACKTEST — NOT the verdict. (Survivorship bias is ~nil here: these are "
                          "the actual index ETFs, not a survivor-selected cross-section.)"),
                "date_range": [sorted(by_date)[0], sorted(by_date)[-1]] if by_date else None,
                "gross": self._stats(hist_gross),
                "net_at_assumed_cost": self._stats(hist_net),
                # decay check: the overnight premium weakened post-2015, so the last ~5y net is the honest read
                "recent_5y_gross": self._stats(hist_gross[-1260:]),
                "recent_5y_net_at_assumed_cost": self._stats(hist_net[-1260:]),
                "cost_sweep": self._cost_sweep(hist_gross),
            },
            "note": ("Overnight (close->open) premium, equal-weight, cost-net. Orthogonal to the VRP vol "
                     "premium; traded as cheap equity. The FORWARD_SHADOW earns the verdict; the historical "
                     "context is in-sample and survivor-biased. Overnight premia have weakened since ~2015, "
                     "so the net-of-cost forward series is the honest test."),
            "status": "OVERNIGHT_ANOMALY_SHADOW",
        }
