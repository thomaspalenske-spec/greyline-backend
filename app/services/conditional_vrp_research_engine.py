"""Conditional Variance Risk Premium — sell vol ONLY when it is rich, away from earnings.

The unconditional VRP is real but too small to trade (see VRPResearchEngine): +1 vol point,
~180bps of premium edge against a ~600bps hurdle. But the VRP is not uniform in time. It is a
RISK premium — you are paid to bear the chance that realized vol blows through implied — and that
payment is largest exactly when implied vol is already elevated (high IV rank) and smallest when
vol is cheap. A plausibility scan showed conditioning on rich IV lifts the premium ~10x. This
engine tests that RIGOROUSLY, fixing the two things the scan did loosely:

  CAUSAL IV RANK. The scan ranked each day's IV against the WHOLE year — which peeks at the
  future distribution. Here IV rank at date t uses only IV observed UP TO t (trailing 252). You
  could actually have known it in real time.

  EARNINGS ARE EXCLUDED. The VRP tail lives at earnings: a single announcement can realize a move
  that dwarfs any implied. Selling premium THROUGH an earnings date is a different trade (that is
  what the earnings-vol engine studies) and it is where the catastrophic losses concentrate. Any
  entry whose forward window contains an earnings report is dropped, so what remains is the
  systematic, non-event VRP.

EVERYTHING ELSE STAYS HONEST: forward-aligned outcomes (completed windows only), monthly cohort
inference (overlap + market-wide-vol correlation safe), sign-flip permutation, DUAL-SOURCE
realized vol (UW + TradeStation), mandatory tail, and — because for an OPTION significance is not
enough — the edge is reported NET of round-trip cost across a range, with the BREAK-EVEN cost
stated, so you can see exactly how cheap execution must be for this to pay. The cost-aware
selection work is what makes the low end of that range reachable.

Survivorship: series are for names that exist today -> any positive result is an UPPER bound.
Power: conditioning shrinks the sample; ~1yr of data gives few monthly units. Reported, not hidden.
"""

import json
import math
import statistics
from datetime import datetime
from pathlib import Path

from app.services.vrp_research_engine import VRPResearchEngine


class ConditionalVRPResearchEngine:

    EARN_DIR = Path("app/data/earnings")
    OUT = Path("app/data/research/conditional_vrp_study.json")

    IVRANK_LOOKBACK = 252          # trailing observations for a causal IV rank
    TERCILE, DECILE = 0.67, 0.90   # "rich IV" thresholds tested
    COST_LEVELS_BPS = [100, 150, 200, 300]
    REALISTIC_COST_BPS = 150       # a liquid ATM straddle round-trip under cost-aware selection
    MIN_ENTRIES = 100
    MIN_NAMES_PER_MONTH = 4
    PERMUTATIONS = 5000
    SEED = 20260724
    FAMILY_WISE_P = 0.0125

    def __init__(self):
        self.vrp = VRPResearchEngine()

    # ------------------------------------------------------------ data

    def _earnings_dates(self, ticker):
        p = self.EARN_DIR / f"{ticker}.json"
        if not p.exists():
            return []
        try:
            rows = json.loads(p.read_text())
        except Exception:
            return []
        return sorted({str(r.get("report_date"))[:10] for r in (rows or []) if r.get("report_date")})

    @staticmethod
    def _trailing_rank(values, i, lookback):
        """Percentile of values[i] within the trailing `lookback` observations up to i (causal)."""
        lo = max(0, i - lookback + 1)
        window = values[lo:i + 1]
        if len(window) < 20:
            return None
        cur = values[i]
        return sum(1 for v in window if v <= cur) / len(window)

    def _entries(self, ticker, asof):
        """Per-name entries with causal IV rank, forward VRP (UW & TS), earnings-window flag."""
        raw = self.vrp._fetch(ticker)
        rows = []
        for x in raw:
            d = str(x.get("date") or "")[:10]
            urv = str(x.get("unshifted_rv_date") or "")[:10]
            iv = self.vrp._f(x.get("implied_volatility"))
            rv = self.vrp._f(x.get("realized_volatility"))
            if d and iv is not None:
                rows.append((d, urv, iv, rv))
        rows.sort(key=lambda r: r[0])
        ivs = [r[2] for r in rows]
        ts_rv = self.vrp._ts_forward_rv(ticker, asof)
        earn = self._earnings_dates(ticker)

        out = []
        for i, (d, urv, iv, uw_rv) in enumerate(rows):
            if not urv or urv >= asof or uw_rv is None or iv <= 0:
                continue                                   # need a completed forward window + valid iv
            rank = self._trailing_rank(ivs, i, self.IVRANK_LOOKBACK)
            if rank is None:
                continue
            earnings_in_window = any(d < e <= urv for e in earn)
            out.append({
                "date": d, "month": d[:7], "iv": iv, "uw_rv": uw_rv,
                "ts_rv": ts_rv.get(d), "iv_rank": rank,
                "earnings_in_window": earnings_in_window,
            })
        return out

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _edge_bps(iv, rv):
        """Vol-selling edge in bps of premium: ~0.5*(IV-RV)/IV (ATM straddle vega/premium)."""
        if rv is None or iv <= 0:
            return None
        return 0.5 * (iv - rv) / iv * 10000

    @staticmethod
    def _sign_flip_p(values, observed, rng, n_perm):
        if not values:
            return 1.0
        hits = 0
        for _ in range(n_perm):
            m = sum(v if rng.random() < 0.5 else -v for v in values) / len(values)
            if abs(m) >= abs(observed):
                hits += 1
        return (hits + 1) / (n_perm + 1)

    def _monthly(self, entries, source):
        """Cross-sectional mean gross edge bps per month (the unit of inference)."""
        by_month = {}
        for e in entries:
            rv = e["uw_rv"] if source == "uw" else e["ts_rv"]
            eb = self._edge_bps(e["iv"], rv)
            if eb is not None:
                by_month.setdefault(e["month"], []).append(eb)
        monthly = [(m, statistics.mean(v)) for m, v in sorted(by_month.items())
                   if len(v) >= self.MIN_NAMES_PER_MONTH]
        return monthly

    # ------------------------------------------------------------ study

    def _analyze(self, entries_all, threshold, rng):
        """Full read for one IV-rank threshold: high-bucket edge, net-of-cost, tail, inference."""
        hi = [e for e in entries_all if e["iv_rank"] >= threshold and not e["earnings_in_window"]]
        lo = [e for e in entries_all if e["iv_rank"] <= (1 - threshold) and not e["earnings_in_window"]]
        if len(hi) < self.MIN_ENTRIES:
            return {"status": "INSUFFICIENT_ENTRIES", "entries": len(hi), "threshold": threshold}

        monthly_uw = self._monthly(hi, "uw")
        monthly_ts = self._monthly(hi, "ts")
        if len(monthly_uw) < 4:
            return {"status": "INSUFFICIENT_MONTHS", "months": len(monthly_uw), "threshold": threshold}

        m_uw = [v for _, v in monthly_uw]
        gross_uw = statistics.mean(m_uw)
        gross_ts = statistics.mean([v for _, v in monthly_ts]) if monthly_ts else None
        sd = statistics.pstdev(m_uw) or 1e-9
        p = self._sign_flip_p(m_uw, gross_uw, rng, self.PERMUTATIONS)

        # low-IV comparison (the conditioning effect)
        lo_monthly = self._monthly(lo, "uw")
        gross_lo = statistics.mean([v for _, v in lo_monthly]) if lo_monthly else None

        # net of cost + break-even
        net = {f"{c}bps": round(gross_uw - c, 1) for c in self.COST_LEVELS_BPS}
        break_even = round(gross_uw, 1)
        net_real = gross_uw - self.REALISTIC_COST_BPS
        sharpe_gross = round(gross_uw / sd * math.sqrt(12), 2)
        sharpe_net_real = round(net_real / sd * math.sqrt(12), 2)

        # tail at the realistic cost
        net_months = [v - self.REALISTIC_COST_BPS for v in m_uw]
        worst = min(monthly_uw, key=lambda x: x[1])
        skew = statistics.mean([(v - gross_uw) ** 3 for v in m_uw]) / (sd ** 3)

        significant = p < self.FAMILY_WISE_P
        tradeable = net_real > 0
        return {
            "threshold_iv_rank": threshold,
            "entries_high_iv": len(hi), "entries_low_iv": len(lo),
            "months": len(monthly_uw),
            "gross_edge_bps_uw": round(gross_uw, 1),
            "gross_edge_bps_ts": round(gross_ts, 1) if gross_ts is not None else None,
            "low_iv_edge_bps_uw": round(gross_lo, 1) if gross_lo is not None else None,
            "conditioning_lift_bps": round(gross_uw - gross_lo, 1) if gross_lo is not None else None,
            "net_edge_bps_by_cost": net,
            "break_even_cost_bps": break_even,
            "net_edge_at_realistic_cost_bps": round(net_real, 1),
            "realistic_cost_bps": self.REALISTIC_COST_BPS,
            "sharpe_gross_annualized": sharpe_gross,
            "sharpe_net_realistic_annualized": sharpe_net_real,
            "p_value": round(p, 4),
            "significant_after_family_wise": bool(significant),
            "tail": {
                "worst_month": {"month": worst[0], "gross_bps": round(worst[1], 1)},
                "pct_negative_months_net": round(sum(1 for v in net_months if v < 0) / len(net_months), 3),
                "skew_monthly": round(skew, 3),
            },
            "verdict": (
                "CONDITIONAL_VRP_TRADEABLE_EDGE" if (significant and tradeable) else
                "PROMISING_NET_POSITIVE_BUT_UNDERPOWERED" if (tradeable and not significant) else
                "SIGNIFICANT_BUT_NET_NEGATIVE_AFTER_COST" if (significant and not tradeable) else
                "NOT_YET_AN_EDGE"),
            "status": "ANALYZED",
        }

    def run(self, names=None, save=True):
        import random
        asof = datetime.utcnow().date().isoformat()
        names = names or self.vrp.DEFAULT_NAMES
        rng = random.Random(self.SEED)

        entries_all, names_used, earn_excluded = [], 0, 0
        for t in names:
            e = self._entries(t, asof)
            if len(e) >= 40:
                names_used += 1
                earn_excluded += sum(1 for x in e if x["earnings_in_window"])
                entries_all.extend(e)
        if names_used < 10:
            return {"status": "INSUFFICIENT_DATA", "names_used": names_used}

        tercile = self._analyze(entries_all, self.TERCILE, rng)
        decile = self._analyze(entries_all, self.DECILE, rng)

        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ConditionalVRPResearchEngine",
            "hypothesis": "VRP captured only when IV is rich (causal trailing rank) and away from "
                          "earnings clears option cost after fees",
            "as_of": asof,
            "names_used": names_used,
            "total_entries": len(entries_all),
            "earnings_windows_excluded": earn_excluded,
            "design": {
                "iv_rank": "CAUSAL trailing 252-obs percentile (no full-sample peek)",
                "earnings": "entries whose forward window contains an earnings report are EXCLUDED",
                "outcome": "forward-aligned VRP, completed windows only",
                "edge_model": "0.5*(IV-RV)/IV in bps of premium (ATM straddle vega/premium)",
                "inference": "monthly cohort sign-flip permutation",
                "realized_sources": "UW and TradeStation (dual-source)",
                "cost_treatment": "reported NET across cost levels + break-even; significance alone "
                                  "is insufficient for an option trade",
            },
            "by_rich_threshold": {"tercile_top33": tercile, "decile_top10": decile},
            "power_caveat": "conditioning shrinks the sample and ~1yr of UW data gives few monthly "
                            "units — a null is weak evidence; treat a positive as suggestive",
            "survivorship": "current names only -> any positive result is an UPPER bound",
            "status": "CONDITIONAL_VRP_STUDY_COMPLETE",
        }
        # headline verdict from the tercile read (more entries -> more stable than the decile)
        out["headline_verdict"] = (tercile or {}).get("verdict", "INSUFFICIENT")
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(json.dumps(out, indent=2))
            except Exception:
                pass
        return out

    def last_study(self):
        try:
            return json.loads(self.OUT.read_text())
        except Exception:
            return None
