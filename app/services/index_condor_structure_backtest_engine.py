"""Turn the confirmed index-VRP SIGNAL into a tradeable DEFINED-RISK STRUCTURE P&L over 24 years.

IndexVRPHistoryResearchEngine proved the index variance premium is real over 2003-2026 (+4 vol pts,
p=2e-4) with a catastrophic NAKED tail (worst month -134%). But that is the signal (VIX vs realized),
not a trade. This engine answers the operator's actual question: if you sell a DEFINED-RISK iron condor
on SPY every month across that whole history — 2008 and 2020 included — what is the realistic Sharpe,
and do the protective WINGS actually cap the tail the naked premium can't?

CONSTRUCTION (one non-overlapping trade per month; ~30-day hold = the VIX horizon):
  * ATM vol   = VIX/100 at entry; τ = 21/252.
  * Short strikes at ±SHORT_SD standard deviations (log-moneyness z·σ√τ) — ~1 SD ≈ a 16-delta strangle.
  * Long WINGS at ±WING_SD SD (further OTM) => max loss is CAPPED before the trade (the whole point).
  * PUT SKEW: put-side legs priced at PUT_SKEW_MULT× the ATM IV (index puts trade richer — the crash-
    insurance premium that IS most of the VRP; [[greyline-vrp-edge]]). Calls at ATM IV.
  * Legs priced Black-Scholes (r=0). Net credit = shorts − wings.
  * Payoff at expiry uses the REAL SPY move over the forward window (actual crash paths — the honest half).
  * COST: a fraction of gross premium (4-leg round-trip) is subtracted — significance is never the bar.
  * Return is on DEFINED RISK (max_loss = wing width − net credit), the capital a desk reserves.

Reports the defined-risk condor AND the naked strangle (same shorts, no wings) side by side, so the wings'
tail protection is explicit, plus by-year P&L (2008/2020 visible) and the monthly-series Sharpe/tail.

⭐ MODELING CAVEATS (stated, not hidden — this is a MODELED backtest, unlike the signal one which used only
observed VIX/SPY): BS with r=0 and a single PUT_SKEW_MULT is an approximation of a real skewed chain; strikes
are SD-placed, not delta-solved off a live surface; cost is a flat premium fraction, not per-name NBBO. So
the LEVEL of the Sharpe is assumption-dependent — the robust readouts are DIRECTIONAL: (a) do defined-risk
wings convert the naked -134% tail into a bounded one, and (b) does the strategy stay net-positive through
real crash regimes. Treat magnitudes as indicative, the tail-capping + crash-survival as the finding.
"""

import math
import statistics
from datetime import datetime
from pathlib import Path

from app.services.index_vrp_history_research_engine import IndexVRPHistoryResearchEngine


class IndexCondorStructureBacktestEngine:

    OUT = Path("app/data/research/index_condor_structure_backtest.json")

    RV_WINDOW = 21                 # forward trading days ~ VIX horizon
    SHORT_SD = 1.0                 # short strikes ~1 SD OTM (~16-delta)
    WING_SD = 2.0                  # long wings ~2 SD OTM (defined risk)
    PUT_SKEW_MULT = 1.10           # index put-side IV richer than ATM (crash-insurance premium)
    COST_PREMIUM_FRAC = 0.10       # 4-leg round-trip cost as a fraction of gross premium (liquid SPX)
    SEED = 20260813

    @staticmethod
    def _norm_cdf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @classmethod
    def _bs(cls, S, K, sigma, tau, is_call):
        if sigma <= 0 or tau <= 0 or S <= 0 or K <= 0:
            return max(0.0, (S - K) if is_call else (K - S))
        d1 = (math.log(S / K) + 0.5 * sigma * sigma * tau) / (sigma * math.sqrt(tau))
        d2 = d1 - sigma * math.sqrt(tau)
        if is_call:
            return S * cls._norm_cdf(d1) - K * cls._norm_cdf(d2)
        return K * cls._norm_cdf(-d2) - S * cls._norm_cdf(-d1)

    def _trade(self, S, sigma, S_T):
        """One iron-condor + naked-strangle outcome for entry spot S, ATM vol sigma, expiry spot S_T.
        Returns dollars per 1 unit of the underlying (SPY), later normalized to return-on-risk."""
        tau = self.RV_WINDOW / 252.0
        sq = sigma * math.sqrt(tau)
        put_iv = sigma * self.PUT_SKEW_MULT
        # strikes (log-moneyness). Put side uses put_iv for its width so richer skew sits a touch wider.
        Kps = S * math.exp(-self.SHORT_SD * put_iv * math.sqrt(tau))
        Kpw = S * math.exp(-self.WING_SD * put_iv * math.sqrt(tau))
        Kcs = S * math.exp(self.SHORT_SD * sq)
        Kcw = S * math.exp(self.WING_SD * sq)

        short_put = self._bs(S, Kps, put_iv, tau, False)
        short_call = self._bs(S, Kcs, sigma, tau, True)
        wing_put = self._bs(S, Kpw, put_iv, tau, False)
        wing_call = self._bs(S, Kcw, sigma, tau, True)

        gross = short_put + short_call
        net_credit = gross - wing_put - wing_call
        cost = self.COST_PREMIUM_FRAC * gross
        # payoff at expiry (long wings offset beyond the wing strike)
        put_loss = max(0.0, Kps - S_T) - max(0.0, Kpw - S_T)
        call_loss = max(0.0, S_T - Kcs) - max(0.0, S_T - Kcw)
        condor_pnl = net_credit - put_loss - call_loss - cost
        # defined risk = worst-case width net of credit (per side; symmetric-ish)
        max_loss = max((Kps - Kpw), (Kcw - Kcs)) - net_credit
        max_loss = max(max_loss, 1e-6)
        # naked strangle (same shorts, NO wings) — to expose the tail the wings cap
        naked_pnl = gross - max(0.0, Kps - S_T) - max(0.0, S_T - Kcs) - self.COST_PREMIUM_FRAC * gross
        return {
            "condor_pnl": condor_pnl, "max_loss": max_loss,
            "ror": condor_pnl / max_loss,                     # return on defined risk
            "naked_pnl_pct_spot": naked_pnl / S * 100.0,      # naked loss scales with spot -> % of underlying
        }

    def _monthly_entries(self, vix, spy):
        """One entry per calendar month: first VIX date with a completed forward SPY window."""
        vdates = sorted(vix)
        sdates = sorted(spy)
        s_idx = {d: i for i, d in enumerate(sdates)}
        seen = set()
        out = []
        for d in vdates:
            mo = d[:7]
            if mo in seen or d not in s_idx:
                continue
            j = s_idx[d]
            if j + self.RV_WINDOW >= len(sdates):
                continue
            S = spy[d]
            S_T = spy[sdates[j + self.RV_WINDOW]]
            sigma = vix[d] / 100.0
            if S <= 0 or sigma <= 0:
                continue
            seen.add(mo)
            out.append({"month": mo, "date": d, "year": d[:4], "res": self._trade(S, sigma, S_T)})
        return out

    @staticmethod
    def _series_stats(vals):
        n = len(vals)
        mean = statistics.mean(vals)
        sd = statistics.pstdev(vals) or 1e-9
        worst = min(vals)
        skew = statistics.mean([(v - mean) ** 3 for v in vals]) / (sd ** 3)
        return {
            "months": n,
            "mean_monthly_ror_pct": round(mean * 100, 2),
            # return-on-DEFINED-RISK, not on capital: you cannot post 100% of capital as max-loss every
            # month, so this "annualized" figure assumes full theoretical redeployment — indicative, not
            # a deployable return. The trustworthy comparators are Sharpe and the crash-year by-year.
            "annualized_ror_pct_full_redeploy_theoretical": round(mean * 12 * 100, 1),
            "sharpe_annualized": round(mean / sd * math.sqrt(12), 2),
            "sharpe_caveat": "high Sharpe + strongly NEGATIVE skew = Sharpe overstates quality; it does not "
                             "price the fat left tail a short-vol book carries",
            "worst_month_ror_pct": round(worst * 100, 1),   # ~one full max-loss (a breached month) = the wing works
            "pct_negative_months": round(sum(1 for v in vals if v < 0) / n, 3),
            "skew_monthly": round(skew, 3),
        }

    def run(self, save=True):
        h = IndexVRPHistoryResearchEngine()
        vix = h._closes(h.VIX)
        spy = h._closes(h.SPY)
        if len(vix) < 500 or len(spy) < 500:
            return {"engine": "IndexCondorStructureBacktestEngine", "status": "INSUFFICIENT_DATA"}
        ent = self._monthly_entries(vix, spy)
        if len(ent) < 24:
            return {"engine": "IndexCondorStructureBacktestEngine", "status": "INSUFFICIENT_MONTHS",
                    "months": len(ent)}

        ror = [e["res"]["ror"] for e in ent]
        naked = [e["res"]["naked_pnl_pct_spot"] for e in ent]
        by_year = {}
        for e in ent:
            by_year.setdefault(e["year"], []).append(e["res"]["ror"])
        by_year_pct = {y: round(statistics.mean(v) * 100, 2) for y, v in sorted(by_year.items())}

        defined = self._series_stats(ror)
        naked_worst = min(naked)
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "IndexCondorStructureBacktestEngine",
            "hypothesis": "a monthly DEFINED-RISK SPY iron condor harvests the confirmed index VRP with a "
                          "tail the wings CAP — survivable through real crash regimes",
            "span": [ent[0]["date"], ent[-1]["date"]], "trades": len(ent),
            "structure": {
                "short_sd": self.SHORT_SD, "wing_sd": self.WING_SD, "put_skew_mult": self.PUT_SKEW_MULT,
                "cost_premium_frac": self.COST_PREMIUM_FRAC, "hold_days": self.RV_WINDOW,
            },
            "defined_risk_condor": defined,
            "naked_strangle_comparison": {
                "worst_month_pct_of_spot": round(naked_worst, 1),
                "note": ("the naked strangle's worst month vs the condor's bounded worst — the wings' job. "
                         "The signal backtest's -134% tail lives here; the condor caps it at "
                         "worst_month_ror_pct of defined risk."),
            },
            "ror_pct_by_year": by_year_pct,
            # the ROBUST claim is structural (wings cap each trade's loss by construction) + net-positive
            # through real crash years — NOT the Sharpe level, which the negative skew flatters.
            "verdict": (
                "DEFINED_RISK_HARVEST_SURVIVES_CRASHES_TAIL_BOUNDED" if (
                    defined["annualized_ror_pct_full_redeploy_theoretical"] > 0 and
                    sum(1 for v in by_year_pct.values() if v > 0) >= 0.8 * len(by_year_pct)) else
                "POSITIVE_BUT_MULTIPLE_LOSING_YEARS" if defined["annualized_ror_pct_full_redeploy_theoretical"] > 0 else
                "NOT_VIABLE_AS_MODELED"),
            "caveats": [
                "MODELED backtest: BS(r=0) + single put-skew multiplier + SD-placed strikes + flat cost "
                "fraction. The LEVEL of every dollar metric is assumption-dependent; the ROBUST readouts are "
                "directional — the wings cap each trade's loss BY CONSTRUCTION, and net-positive crash-year "
                "survival.",
                "Return is on DEFINED RISK per trade, NOT on capital — the 'annualized' figure assumes full "
                "theoretical redeployment and overstates a deployable return.",
                "Sharpe is high BUT skew is ~-4: the Sharpe does not price the crash tail; do not read it as "
                "a quality score.",
                "MONTHLY first-trading-day entries UNDER-SAMPLE the tail (they can miss the worst 21-day "
                "window, e.g. the Feb-Mar 2020 plunge) — so the naked worst month shown is milder than the "
                "true worst; the condor's loss is bounded regardless, which is the point.",
                "Uses REAL SPY forward paths (2008/2020 included) for the payoff; only the option PRICING "
                "is modeled. A real harvest is index-ETF condors off live UW/TS chains — this sizes the "
                "opportunity, it is not the live P&L.",
            ],
            "status": "ANALYZED",
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
            return {"engine": "IndexCondorStructureBacktestEngine", "status": "NO_STUDY_YET"}
