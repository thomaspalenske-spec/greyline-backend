"""Does dividend-adjusting the signal matter? — the measurement behind wiring the total-return series
into the LIVE momentum-reversal signal.

THE GAP: the live signal (MomentumReversalStrategyEngine._csv_universe) reads PRICE-ONLY closes
(app/data/historical/*_daily.csv), while the backtest that validated the edge reads dividend-adjusted
adj_close. So live and backtest disagree, and — the sharper problem — the 5-day REVERSAL leg misreads an
ex-dividend price DROP as a "recent down move to fade" (a false BULLISH dip signal). This engine quantifies
the cost of that, two ways:

  1. FACTOR A/B: run the identical backtest on price-only vs adj_close (same files/dates/machinery, only the
     price column differs) — the effect on gross return, Sharpe, and breakeven cost.
  2. SIGNAL-FLIP + EX-DIV: at each weekly rebalance, compute the signal on BOTH series per name; count how
     often the confirmed bias FLIPS, and how many flips sit within the reversal window of a DISTRIBUTION day
     (a date where the adjusted and price daily returns diverge = a dividend/spinoff ex-date). Those are the
     ex-div false reversals adjustment removes."""

import json
from datetime import datetime
from pathlib import Path

from app.services.momentum_reversal_backtest_engine import MomentumReversalBacktestEngine


class TotalReturnSignalImpactEngine:

    DISTRIBUTION_EPS = 0.002     # |adj_ret - price_ret| above this on a day == a distribution (ex-div/spinoff)
    CACHE = Path("app/data/research/total_return_signal_impact.json")
    CACHE_TTL_H = 24             # the inputs (daily bars) change at most daily — recompute once/day

    def __init__(self):
        self.bt = MomentumReversalBacktestEngine()

    # ---- 1. factor-level A/B -------------------------------------------------------------------------
    def _factor_ab(self):
        adj = self.bt.run(long_only=True, save=False, price_field="adj_close")
        raw = self.bt.run(long_only=True, save=False, price_field="close")
        keys = ("gross_annualized_pct", "sharpe_annualized_gross", "gross_mean_per_period_bps",
                "hit_rate", "p_value_gross", "breakeven_one_way_cost_bps", "rebalance_periods")
        if adj.get("status") != "MOMENTUM_REVERSAL_BACKTEST_COMPLETE" or \
                raw.get("status") != "MOMENTUM_REVERSAL_BACKTEST_COMPLETE":
            return {"error": "backtest insufficient", "adj_status": adj.get("status"),
                    "raw_status": raw.get("status")}
        return {
            "adjusted": {k: adj.get(k) for k in keys},
            "price_only": {k: raw.get(k) for k in keys},
            "delta_adjusted_minus_price": {
                "gross_annualized_pct": round(adj["gross_annualized_pct"] - raw["gross_annualized_pct"], 2),
                "sharpe": round(adj["sharpe_annualized_gross"] - raw["sharpe_annualized_gross"], 2),
                "breakeven_bps": (None if adj["breakeven_one_way_cost_bps"] is None
                                  or raw["breakeven_one_way_cost_bps"] is None
                                  else adj["breakeven_one_way_cost_bps"] - raw["breakeven_one_way_cost_bps"]),
            },
        }

    # ---- 2. signal-flip + ex-div attribution ---------------------------------------------------------
    def _signal_flip(self):
        bt = self.bt
        adj = bt._load("adj_close")
        raw = bt._load("close")
        syms = [s for s in adj if s in raw]
        if len(syms) < 20:
            return {"error": "insufficient overlapping symbols", "symbols": len(syms)}

        from collections import Counter
        dc = Counter()
        for s in syms:
            dc.update(adj[s].keys())
        dates = sorted(d for d, n in dc.items() if n >= 20)
        a_al = {s: [adj[s].get(d) for d in dates] for s in syms}
        r_al = {s: [raw[s].get(d) for d in dates] for s in syms}

        rebal = range(bt.MOM_START, len(dates) - bt.HOLD_DAYS, bt.HOLD_DAYS)
        evals = confirmed_adj = confirmed_raw = flips = flips_near_distribution = rev_leg_flips = 0
        for i in rebal:
            for s in syms:
                ca, cr = a_al[s], r_al[s]
                if (ca[i] is None or cr[i] is None or ca[i - bt.MOM_START] is None
                        or cr[i - bt.MOM_START] is None or ca[i - bt.MOM_END] is None
                        or cr[i - bt.MOM_END] is None or ca[i - bt.REV_LOOKBACK] is None
                        or cr[i - bt.REV_LOOKBACK] is None):
                    continue
                evals += 1
                ba, _ = bt._signal(ca, i)
                br, _ = bt._signal(cr, i)
                if ba is not None:
                    confirmed_adj += 1
                if br is not None:
                    confirmed_raw += 1
                # reversal-leg sign flip (the ex-div-sensitive leg): sign of the 5-day move differs
                ra = ca[i] / ca[i - bt.REV_LOOKBACK] - 1.0
                rr = cr[i] / cr[i - bt.REV_LOOKBACK] - 1.0
                rev_flipped = (ra > 0) != (rr > 0)
                if rev_flipped:
                    rev_leg_flips += 1
                if ba != br:                                   # confirmed-bias flip (incl. one side None)
                    flips += 1
                    # was there a DISTRIBUTION day inside the reversal window? (adj vs price daily-return gap)
                    near = False
                    for j in range(max(1, i - bt.REV_LOOKBACK), i + 1):
                        aj0, aj1, rj0, rj1 = ca[j - 1], ca[j], cr[j - 1], cr[j]
                        if None in (aj0, aj1, rj0, rj1) or min(aj0, rj0) <= 0:
                            continue
                        if abs((aj1 / aj0 - 1.0) - (rj1 / rj0 - 1.0)) > self.DISTRIBUTION_EPS:
                            near = True
                            break
                    if near:
                        flips_near_distribution += 1
        return {
            "signal_evaluations": evals,
            "confirmed_adjusted": confirmed_adj,
            "confirmed_price_only": confirmed_raw,
            "bias_flips": flips,
            "bias_flips_pct_of_evals": round(flips / evals * 100, 2) if evals else None,
            "reversal_leg_sign_flips": rev_leg_flips,
            "flips_attributable_to_distribution": flips_near_distribution,
            "distribution_attributable_pct_of_flips": (round(flips_near_distribution / flips * 100, 1)
                                                       if flips else None),
        }

    def _cached(self):
        """Return the cached result if it's younger than CACHE_TTL_H, else None. The measurement is a ~28s
        two-backtest computation over daily data that changes at most once a day, so serving a day-old
        result keeps the route instant without going stale."""
        try:
            d = json.loads(self.CACHE.read_text())
            ts = datetime.fromisoformat(d["as_of"])
            if (datetime.utcnow() - ts).total_seconds() < self.CACHE_TTL_H * 3600:
                d["served_from_cache"] = True
                return d
        except Exception:
            pass
        return None

    def run(self, fresh=False):
        if not fresh:
            c = self._cached()
            if c is not None:
                return c
        factor = self._factor_ab()
        flip = self._signal_flip()
        # verdict: is adjustment worth wiring? (better/comparable factor AND a real flip volume, esp. ex-div)
        verdict = "INCONCLUSIVE"
        try:
            d = factor.get("delta_adjusted_minus_price", {})
            sh = d.get("sharpe")
            flips_pct = flip.get("bias_flips_pct_of_evals") or 0
            exdiv_pct = flip.get("distribution_attributable_pct_of_flips") or 0
            if sh is not None and sh >= -0.05 and flips_pct >= 1.0:
                verdict = (f"WIRE IT: adjustment changes {flips_pct}% of signals "
                           f"({exdiv_pct}% of the flips sit on a distribution day = ex-div false reversals "
                           f"removed) with no factor cost (Sharpe delta {sh:+.2f}).")
            elif sh is not None and sh < -0.1:
                verdict = (f"HOLD: price-only actually scores higher on this survivor-only universe "
                           f"(Sharpe delta {sh:+.2f}); wiring would change {flips_pct}% of signals — "
                           f"investigate before flipping.")
            else:
                verdict = (f"MARGINAL: {flips_pct}% of signals flip (ex-div-attributable {exdiv_pct}%), "
                           f"factor Sharpe delta {sh:+.2f} — a correctness fix more than a return lever.")
        except Exception:
            pass
        result = {
            "as_of": datetime.utcnow().isoformat(),
            "factor_ab": factor,
            "signal_flip": flip,
            "verdict": verdict,
            "caveats": [
                "Live signal reads PRICE-ONLY (MomentumReversalStrategyEngine._csv_universe); the backtest "
                "reads adj_close. This measures the gap on the SAME survivor-only universe (biased upward).",
                "A 'distribution day' is inferred where the adjusted and price daily returns diverge "
                f"(>{self.DISTRIBUTION_EPS}) — captures dividends AND spinoffs without a separate feed.",
                "The correctness case (removing ex-div false reversals) stands even if the factor delta is "
                "small — a live signal that misreads an ex-div gap as a dip is simply wrong.",
            ],
            "served_from_cache": False,
            "status": "TOTAL_RETURN_SIGNAL_IMPACT",
        }
        try:
            self.CACHE.parent.mkdir(parents=True, exist_ok=True)
            self.CACHE.write_text(json.dumps(result, indent=2))
        except Exception:
            pass
        return result
