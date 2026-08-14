"""Index variance-risk-premium over the LONG history — the crash-regime + power test the 1-year
UW study structurally cannot run.

GreyLine's one edge that ever cleared significance is the INDEX VRP: selling broad-index vol when
implied is rich pays, because index implied vol systematically exceeds subsequently-realized index
vol (Bollerslev-style variance premium). But every prior cut of it — the dispersion study, the
conditional-VRP study — was measured on the ~1 year of implied-vol history UW provides. One year:
  * is UNDERPOWERED (~11 monthly units), so p sat at 0.14 even where the point estimate was large; and
  * contains NO major crash, so it structurally UNDERSTATES the left tail of a short-vol strategy —
    the single most important thing to know before selling premium.
You cannot fix either by re-analysing that year. But the INDEX implied series does not depend on UW:
the VIX IS 30-day index implied vol, and it is on disk back to 2002 (app/data/research/vol_term_structure/
VIX.csv), with SPY closes back to 1998 for the realized side. So the exact same edge can be backtested
across 2003-2026 — 2008, 2011, 2015, 2018, 2020, 2022 all included — with ~20x the monthly units and,
finally, real crash regimes in the sample.

METHOD (identical inference discipline to ConditionalVRPResearchEngine — this REUSES its helpers, it
does not re-implement them):
  * IMPLIED  iv[t]  = VIX close / 100  (30-day fair index implied vol).
  * REALIZED rv[t]  = annualized close-to-close SPY vol over the FORWARD [t+1, t+21] window (~30
    calendar days, the VIX horizon). Forward-aligned + completed-window-only => NO look-ahead. (Close-
    to-close ignores intraday range, so it mildly UNDERSTATES realized => the VRP here is a slight
    UPPER bound, stated not hidden.)
  * RICH IV = CAUSAL trailing-252 VIX percentile (reuses C._trailing_rank) — knowable in real time.
  * EDGE    = 0.5*(iv-rv)/iv in bps of premium (reuses C._edge_bps), AND the index-native VRP in vol
    points (iv-rv), directly comparable to the dispersion study's CI [+1.48,+3.66].
  * OVERLAP/AUTOCORRELATION: daily 30-day windows overlap ~95% -> the unit of inference is the calendar
    MONTH (one mean per month). Adjacent months' windows barely overlap => ~independent.
  * INFERENCE: sign-flip permutation on the monthly series (reuses C._sign_flip_p) — fat-tailed, robust.
  * TAIL + CRISIS: worst month, % negative, skew, AND VRP by calendar year so 2008/2020 are explicit.
  * COST: net across the same cost levels + break-even, so significance is never mistaken for tradeable.

No earnings exclusion (an index has no single earnings event; macro shocks ARE the systemic premium).
This backtests the SIGNAL and its tail, not a specific tradeable structure — you cannot trade the VIX
itself; a real harvest is index options / a variance swap, which carries its own frictions. It answers
the question the 1-year study cannot: does the index VRP survive real crashes, with power?
"""

import csv
import math
import statistics
from datetime import datetime
from pathlib import Path

from app.services.conditional_vrp_research_engine import ConditionalVRPResearchEngine as C


class IndexVRPHistoryResearchEngine:

    VIX = Path("app/data/research/vol_term_structure/VIX.csv")
    SPY = Path("app/data/historical/SPY_daily.csv")
    OUT = Path("app/data/research/index_vrp_history_study.json")

    RV_WINDOW = 21                 # forward trading days ~ VIX's 30 calendar days
    IVRANK_LOOKBACK = C.IVRANK_LOOKBACK
    TERCILE, DECILE = C.TERCILE, C.DECILE
    COST_LEVELS_BPS = C.COST_LEVELS_BPS
    REALISTIC_COST_BPS = C.REALISTIC_COST_BPS
    PERMUTATIONS = C.PERMUTATIONS
    SEED = C.SEED
    FAMILY_WISE_P = C.FAMILY_WISE_P
    MIN_DAYS_PER_MONTH = 5         # a month needs this many entry days to be one cohort unit
    MIN_MONTHS = 24                # don't offer a verdict on fewer

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _closes(self, path):
        out = {}
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    c = self._f(r.get("close"))
                    d = str(r.get("date") or "")[:10]
                    if d and c and c > 0:
                        out[d] = c
        except Exception:
            return {}
        return out

    def _entries(self):
        """One entry per date with a completed forward realized window: causal VIX rank + forward VRP."""
        vix = self._closes(self.VIX)                       # index implied (points)
        spy = self._closes(self.SPY)                       # realized side
        vdates = sorted(vix)
        sdates = sorted(spy)
        s_idx = {d: i for i, d in enumerate(sdates)}
        # daily SPY log returns for the forward realized window
        logret = {}
        for i in range(1, len(sdates)):
            p0, p1 = spy[sdates[i - 1]], spy[sdates[i]]
            if p0 > 0 and p1 > 0:
                logret[sdates[i]] = math.log(p1 / p0)

        vix_vals = [vix[d] for d in vdates]
        entries = []
        for i, d in enumerate(vdates):
            iv = vix_vals[i] / 100.0
            if iv <= 0 or d not in s_idx:
                continue
            j = s_idx[d]
            fwd = sdates[j + 1:j + 1 + self.RV_WINDOW]
            if len(fwd) < self.RV_WINDOW:                  # completed forward window only (no look-ahead)
                continue
            rets = [logret[x] for x in fwd if x in logret]
            if len(rets) < self.RV_WINDOW - 1:
                continue
            rv = statistics.pstdev(rets) * math.sqrt(252)  # annualized forward realized vol
            rank = C._trailing_rank(vix_vals, i, self.IVRANK_LOOKBACK)  # causal, reused
            if rank is None:
                continue
            entries.append({"date": d, "month": d[:7], "year": d[:4], "iv": iv, "rv": rv, "iv_rank": rank})
        return entries

    def _monthly(self, entries, key):
        """Collapse each month's daily entries to one mean (the unit of inference). key: 'bps' | 'volpts'."""
        by_month = {}
        for e in entries:
            val = C._edge_bps(e["iv"], e["rv"]) if key == "bps" else (e["iv"] - e["rv"]) * 100.0
            if val is not None:
                by_month.setdefault(e["month"], []).append(val)
        return [(m, statistics.mean(v)) for m, v in sorted(by_month.items())
                if len(v) >= self.MIN_DAYS_PER_MONTH]

    def _analyze(self, entries_all, threshold, rng):
        hi = [e for e in entries_all if e["iv_rank"] >= threshold]
        lo = [e for e in entries_all if e["iv_rank"] <= (1 - threshold)]
        m_bps = self._monthly(hi, "bps")
        m_vp = self._monthly(hi, "volpts")
        if len(m_bps) < self.MIN_MONTHS:
            return {"threshold_iv_rank": threshold, "status": "INSUFFICIENT_MONTHS", "months": len(m_bps)}

        bps = [v for _, v in m_bps]
        vp = [v for _, v in m_vp]
        gross = statistics.mean(bps)
        gross_vp = statistics.mean(vp)
        sd = statistics.pstdev(bps) or 1e-9
        p = C._sign_flip_p(bps, gross, rng, self.PERMUTATIONS)

        lo_bps = [v for _, v in self._monthly(lo, "bps")]
        gross_lo = statistics.mean(lo_bps) if lo_bps else None

        net = {f"{c}bps": round(gross - c, 1) for c in self.COST_LEVELS_BPS}
        net_real = gross - self.REALISTIC_COST_BPS
        net_months = [v - self.REALISTIC_COST_BPS for v in bps]
        worst = min(m_bps, key=lambda x: x[1])
        skew = statistics.mean([(v - gross) ** 3 for v in bps]) / (sd ** 3)
        significant = p < self.FAMILY_WISE_P
        tradeable = net_real > 0
        return {
            "threshold_iv_rank": threshold,
            "months": len(m_bps), "entry_days_high_iv": len(hi), "entry_days_low_iv": len(lo),
            "gross_edge_bps": round(gross, 1),
            "gross_vrp_vol_points": round(gross_vp, 2),
            "low_iv_edge_bps": round(gross_lo, 1) if gross_lo is not None else None,
            "conditioning_lift_bps": round(gross - gross_lo, 1) if gross_lo is not None else None,
            "net_edge_bps_by_cost": net,
            "break_even_cost_bps": round(gross, 1),
            "net_edge_at_realistic_cost_bps": round(net_real, 1),
            "realistic_cost_bps": self.REALISTIC_COST_BPS,
            "sharpe_gross_annualized": round(gross / sd * math.sqrt(12), 2),
            "sharpe_net_realistic_annualized": round(net_real / sd * math.sqrt(12), 2),
            "p_value": round(p, 4),
            "significant_after_family_wise": bool(significant),
            "tail": {
                "worst_month": {"month": worst[0], "gross_bps": round(worst[1], 1)},
                "pct_negative_months_net": round(sum(1 for v in net_months if v < 0) / len(net_months), 3),
                "skew_monthly": round(skew, 3),
            },
            "verdict": (
                "INDEX_VRP_TRADEABLE_EDGE" if (significant and tradeable) else
                "SIGNIFICANT_BUT_NET_NEGATIVE_AFTER_COST" if (significant and not tradeable) else
                "PROMISING_NET_POSITIVE_BUT_UNDERPOWERED" if (tradeable and not significant) else
                "NOT_YET_AN_EDGE"),
            "status": "ANALYZED",
        }

    def _by_year(self, entries):
        """Mean VRP (vol points) per calendar year — the crash-regime tail the 1-year study cannot show."""
        by_year = {}
        for e in entries:
            by_year.setdefault(e["year"], []).append((e["iv"] - e["rv"]) * 100.0)
        return {y: round(statistics.mean(v), 2) for y, v in sorted(by_year.items())}

    def run(self, save=True):
        import random
        rng = random.Random(self.SEED)
        entries = self._entries()
        if len(entries) < 500:
            return {"engine": "IndexVRPHistoryResearchEngine", "status": "INSUFFICIENT_DATA",
                    "entries": len(entries)}
        span = [entries[0]["date"], entries[-1]["date"]]
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "IndexVRPHistoryResearchEngine",
            "hypothesis": "index implied vol (VIX) systematically exceeds forward realized index vol, and "
                          "the premium is larger when implied is rich (causal VIX rank) — over a horizon "
                          "long enough to include real crash regimes",
            "span": span, "entry_days": len(entries),
            "implied_source": "VIX (30-day index implied vol), on disk to 2002",
            "realized_source": "SPY close-to-close, forward 21-trading-day annualized (VIX horizon)",
            "design": {
                "look_ahead": "forward-aligned realized, completed windows only; causal trailing-252 VIX rank",
                "inference": "monthly cohort sign-flip permutation (overlap + market-wide-vol safe)",
                "edge_model": "0.5*(IV-RV)/IV bps + native VRP in vol points",
                "cost_treatment": "net across cost levels + break-even",
                "caveats": "close-to-close realized => VRP is a mild upper bound; VIX is not directly "
                           "tradeable, so this tests the SIGNAL+tail, not a specific structure's frictions; "
                           "index VRP is a RISK premium — the crash tail is the point, not a flaw",
            },
            "vrp_vol_points_by_year": self._by_year(entries),
            "unconditional": self._analyze(entries, 0.0, rng),
            "rich_iv_tercile": self._analyze(entries, self.TERCILE, rng),
            "rich_iv_decile": self._analyze(entries, self.DECILE, rng),
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(__import__("json").dumps(result, indent=2))
            except Exception:
                pass
        return result

    def last_study(self):
        try:
            return __import__("json").loads(self.OUT.read_text())
        except Exception:
            return {"engine": "IndexVRPHistoryResearchEngine", "status": "NO_STUDY_YET"}
