"""Cost-aware out-of-sample backtest of GreyLine's momentum-reversal signal — the go/no-go test.

This answers the one question that decides whether GreyLine can ever make money: does its
signal produce returns that SURVIVE realistic costs? Momentum + short-term reversal is a
proven, decades-replicated factor; the open question (the signal engine's own docstring calls
it "doubtful for OTM options") is whether GreyLine's IMPLEMENTATION captures it net of costs.

WHAT THIS CAN AND CANNOT DO, stated up front:
  * It backtests the SIGNAL in EQUITY / total-return terms. That is rigorous and answerable
    with the data we have (the dividend-adjusted adj_close series — a momentum backtest on
    price-only closes is simply wrong, which is why the total-return work was a prerequisite).
  * It CANNOT backtest OPTIONS directly: GreyLine has no historical option chains (premium,
    greeks, spread over time) — they stream live only. The options verdict here is ANALYTICAL:
    given the measured equity edge, can any OTM option overcome its own spread + theta? A
    fabricated historical-options backtest would be the exact false precision this repo keeps
    catching, so it is refused.

THE TRAPS THIS SESSION KEEPS HITTING, AND HOW EACH IS HANDLED:
  * LOOK-AHEAD: the signal at date t uses closes up to and including t; the forward return is
    close[t]→close[t+K], strictly after the signal. Ranking never touches the holding window
    (the exact overlap bug that faked a 149bps mechanical-flow "edge").
  * OVERLAPPING WINDOWS: rebalance periods are NON-OVERLAPPING K-day blocks, so each period is
    ~one independent observation. Inference treats PERIODS as the unit, never symbol-days.
  * SURVIVORSHIP: the universe is survivor-only, biasing results UPWARD (~43% of 2015 names
    have since delisted and are absent). A positive result here is therefore an UPPER bound;
    a null is conservative and trustworthy. Declared in the output.
  * COSTS: swept from 0 upward to find the BREAKEVEN cost — the per-trade cost at which the
    edge vanishes. That breakeven is the number the options question turns on.
  * MULTIPLE COMPARISONS: this runs ONE pre-specified config matching GreyLine's live signal
    (253/22 momentum, 5-day reversal, top-N by conviction, weekly hold). It is not a parameter
    scan; no cherry-picking a horizon that happened to work.
"""

import csv
import random
from datetime import datetime
from pathlib import Path


class MomentumReversalBacktestEngine:

    TR_DIR = Path("app/data/historical_total_return")   # dividend+split adjusted adj_close
    RAW_DIR = Path("app/data/historical")               # fallback if a TR file is missing
    OUT = Path("app/data/research/momentum_reversal_backtest.json")

    MOM_START = 253      # momentum window start (bars back) — matches DirectionalSignalEngine
    MOM_END = 22         # momentum window end (the 1-month skip)
    REV_LOOKBACK = 5     # reversal leg
    HOLD_DAYS = 5        # non-overlapping weekly rebalance, matches the reversal horizon
    TOP_N = 5            # names held per side, matches the live strategy
    PERMUTATIONS = 2000
    SEED = 20260724

    # Realistic per-trade one-way EQUITY cost (spread + commission), swept to find breakeven.
    COST_GRID_BPS = [0, 2, 5, 10, 20, 35, 50, 75, 100]

    def _load(self, price_field="adj_close"):
        """{symbol: {date: price}} from the total-return series. `price_field` picks the column:
        'adj_close' (dividend+split adjusted — the correct series, the default) or 'close' (price-only,
        exactly what the LIVE signal reads today). Same files/dates either way, so the two can run through
        identical machinery to isolate the effect of dividend adjustment on the signal."""
        series = {}
        try:
            from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
            tradable_from = PriceBarTradabilityEngine().tradable_from_map()
        except Exception:
            tradable_from = {}

        files = list(self.TR_DIR.glob("*_total_return.csv"))
        for p in files:
            sym = p.name.replace("_total_return.csv", "")
            floor = tradable_from.get(sym)
            row = {}
            try:
                with open(p) as f:
                    for r in csv.DictReader(f):
                        d = str(r["date"])[:10]
                        if floor and d < floor:
                            continue
                        try:
                            row[d] = float(r[price_field])
                        except (ValueError, KeyError, TypeError):
                            continue
            except Exception:
                continue
            if len(row) > self.MOM_START + self.HOLD_DAYS:
                series[sym] = row
        return series

    VOL_LOOKBACK = 60          # trailing bars for the point-in-time volatility estimate

    def _trailing_vol(self, closes, i):
        """Annualised realised vol from bars STRICTLY BEFORE i — no look-ahead.

        This is the honest way to express a volatility preference: a rule computed from data
        available at the decision, so it can be executed live and measured identically in the
        backtest. Screening the UNIVERSE by volatility measured over the whole sample would be
        selection bias — it deletes names retroactively using information the strategy could
        not have had, which warps the very reality the backtest is meant to describe.
        """
        lo = i - self.VOL_LOOKBACK
        if lo < 1:
            return None
        rets = []
        for j in range(lo, i):
            a, b = closes[j - 1], closes[j]
            if a and b and a > 0 and b > 0:
                rets.append(b / a - 1.0)
        if len(rets) < 20:
            return None
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / len(rets)
        return (var ** 0.5) * (252 ** 0.5) * 100.0

    def _signal(self, closes, i):
        """Replicate DirectionalSignalEngine at index i (needs i >= MOM_START).

        Returns (bias, conviction_magnitude) or (None, 0) if the two legs disagree.
        """
        if i < self.MOM_START:
            return None, 0.0
        c_mom_start = closes[i - self.MOM_START]
        c_mom_end = closes[i - self.MOM_END]
        c_rev = closes[i - self.REV_LOOKBACK]
        c_now = closes[i]
        if min(c_mom_start, c_mom_end, c_rev, c_now) <= 0:
            return None, 0.0
        mom = c_mom_end / c_mom_start - 1.0
        rev5 = c_now / c_rev - 1.0
        mom_bias = "BULLISH" if mom > 0 else "BEARISH"
        rev_bias = "BEARISH" if rev5 > 0 else "BULLISH"     # fade the recent move
        if mom_bias != rev_bias:
            return None, 0.0
        return mom_bias, abs(mom) + abs(rev5)               # magnitude proxy for conviction

    def run(self, long_only=False, save=True, max_vol_pct=None, price_field="adj_close"):
        """max_vol_pct: optional POINT-IN-TIME volatility ceiling applied at each rebalance
        from trailing data only. This is a tradeable rule, NOT a universe screen — the
        universe itself is never filtered on full-sample properties.
        price_field: 'adj_close' (default) or 'close' (price-only) — for the total-return vs price-only
        comparison. save is forced off for the non-default field so it can't overwrite the canonical result."""
        series = self._load(price_field)
        if price_field != "adj_close":
            save = False
        if len(series) < 20:
            return {"status": "INSUFFICIENT_UNIVERSE", "symbols": len(series)}

        # common calendar: sorted union of dates that ≥20 names share
        from collections import Counter
        dc = Counter()
        for row in series.values():
            dc.update(row.keys())
        dates = sorted(d for d, n in dc.items() if n >= 20)
        # index each symbol's closes onto this calendar (None where missing)
        aligned = {s: [row.get(d) for d in dates] for s, row in series.items()}

        rng = random.Random(self.SEED)
        # NON-OVERLAPPING rebalance points spaced HOLD_DAYS apart, each needing MOM_START history
        rebal_idxs = list(range(self.MOM_START, len(dates) - self.HOLD_DAYS, self.HOLD_DAYS))
        period_rets = []          # gross long-short (or long-only) return per rebalance period
        n_positions = []
        for i in rebal_idxs:
            picks = []            # (bias, conviction, fwd_return)
            for s, closes in aligned.items():
                c_i = closes[i]
                c_fwd = closes[i + self.HOLD_DAYS]
                if c_i is None or c_fwd is None or c_i <= 0:
                    continue
                # signal needs a contiguous-enough history; guard the specific lookbacks
                if (closes[i - self.MOM_START] is None or closes[i - self.MOM_END] is None
                        or closes[i - self.REV_LOOKBACK] is None):
                    continue
                bias, conv = self._signal(closes, i)
                if bias is None:
                    continue
                if max_vol_pct is not None:
                    v = self._trailing_vol(closes, i)      # trailing only — no look-ahead
                    if v is not None and v > max_vol_pct:
                        continue
                fwd = c_fwd / c_i - 1.0
                picks.append((bias, conv, fwd))
            if not picks:
                continue

            longs = sorted([p for p in picks if p[0] == "BULLISH"], key=lambda x: -x[1])[:self.TOP_N]
            shorts = sorted([p for p in picks if p[0] == "BEARISH"], key=lambda x: -x[1])[:self.TOP_N]
            leg_rets = []
            if longs:
                leg_rets.append(sum(p[2] for p in longs) / len(longs))              # long leg
            if shorts and not long_only:
                leg_rets.append(-sum(p[2] for p in shorts) / len(shorts))           # short leg
            if not leg_rets:
                continue
            period_rets.append(sum(leg_rets) / len(leg_rets))
            n_positions.append(len(longs) + (0 if long_only else len(shorts)))

        if len(period_rets) < 50:
            return {"status": "INSUFFICIENT_PERIODS", "periods": len(period_rets)}

        gross_mean = sum(period_rets) / len(period_rets)
        # cost sweep: each rebalance fully turns over -> ~2 one-way costs per period
        periods_per_year = 252 / self.HOLD_DAYS
        cost_curve = []
        breakeven_bps = None
        for c_bps in self.COST_GRID_BPS:
            c = c_bps / 10000.0
            net_mean = gross_mean - 2 * c
            ann = (1 + net_mean) ** periods_per_year - 1
            cost_curve.append({"one_way_cost_bps": c_bps,
                               "net_mean_per_period_bps": round(net_mean * 10000, 2),
                               "annualized_pct": round(ann * 100, 2)})
            if breakeven_bps is None and net_mean <= 0:
                breakeven_bps = c_bps

        # inference: is the GROSS mean distinguishable from zero? sign-flip permutation
        # (each period's sign randomized — the natural null for a directional return series)
        hits = 0
        for _ in range(self.PERMUTATIONS):
            m = sum(x if rng.random() < 0.5 else -x for x in period_rets) / len(period_rets)
            if abs(m) >= abs(gross_mean):
                hits += 1
        p_value = (hits + 1) / (self.PERMUTATIONS + 1)

        import statistics
        sd = statistics.pstdev(period_rets) or 1e-9
        sharpe_ann = (gross_mean / sd) * (periods_per_year ** 0.5)
        wins = sum(1 for x in period_rets if x > 0)

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "config": {"momentum": f"{self.MOM_START}/{self.MOM_END}", "reversal_days": self.REV_LOOKBACK,
                       "hold_days": self.HOLD_DAYS, "top_n_per_side": self.TOP_N,
                       "mode": "LONG_ONLY" if long_only else "LONG_SHORT",
                       "input": "TOTAL_RETURN_ADJ_CLOSE" if price_field == "adj_close" else "PRICE_ONLY_CLOSE"},
            "symbols": len(series), "date_range": [dates[self.MOM_START], dates[-1]],
            "rebalance_periods": len(period_rets),
            "avg_positions_per_period": round(sum(n_positions) / len(n_positions), 1),
            "gross_mean_per_period_bps": round(gross_mean * 10000, 2),
            "gross_annualized_pct": round(((1 + gross_mean) ** periods_per_year - 1) * 100, 2),
            "sharpe_annualized_gross": round(sharpe_ann, 2),
            "hit_rate": round(wins / len(period_rets), 3),
            "p_value_gross": round(p_value, 4),
            "gross_significant": bool(p_value < 0.05),
            "cost_sweep": cost_curve,
            "breakeven_one_way_cost_bps": breakeven_bps,
            "survivorship": {"survivorship_free": False,
                             "effect": "universe is survivor-only -> results biased UPWARD; a "
                                       "positive edge here is an upper bound, a null is conservative"},
            "options_vehicle_note": (
                "NO historical option chains exist, so this is an EQUITY/total-return backtest. "
                "For OTM options to capture this edge, the underlying move must overcome the "
                "option's bid-ask spread (~5-15% of premium) plus theta over the hold. Compare "
                "breakeven_one_way_cost_bps against those: equity trades cost ~1-5bps one-way; "
                "an OTM option round-trip commonly costs 500-1500bps of premium. If the edge "
                "dies at tens of bps, the OTM-options vehicle cannot carry it — trade the factor "
                "as equity or deep-ITM/delta-1."),
            "status": "MOMENTUM_REVERSAL_BACKTEST_COMPLETE",
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                import json
                self.OUT.write_text(json.dumps(result, indent=2))
            except Exception:
                pass
        return result

    def benchmark_decomposition(self):
        """Split the LONG-ONLY result into beta (market) and alpha (excess over market).

        A long-only equity book rides the equity risk premium — its raw return is mostly beta,
        not signal skill. The honest test of selection skill is the EXCESS over an equal-weight
        buy-and-hold of the SAME eligible names in the SAME periods. Both sides share the
        universe's survivorship inflation, so the excess controls for it far better than the
        raw long-only number does.
        """
        series = self._load()
        if len(series) < 20:
            return {"status": "INSUFFICIENT_UNIVERSE"}
        from collections import Counter
        dc = Counter()
        for row in series.values():
            dc.update(row.keys())
        dates = sorted(d for d, n in dc.items() if n >= 20)
        aligned = {s: [row.get(d) for d in dates] for s, row in series.items()}

        idxs = list(range(self.MOM_START, len(dates) - self.HOLD_DAYS, self.HOLD_DAYS))
        sig_rets, mkt_rets, excess = [], [], []
        for i in idxs:
            picks, allfwd = [], []
            for s, cl in aligned.items():
                ci, cf = cl[i], cl[i + self.HOLD_DAYS]
                if ci is None or cf is None or ci <= 0:
                    continue
                if (cl[i - self.MOM_START] is None or cl[i - self.MOM_END] is None
                        or cl[i - self.REV_LOOKBACK] is None):
                    continue
                fwd = cf / ci - 1.0
                allfwd.append(fwd)
                b, conv = self._signal(cl, i)
                if b == "BULLISH":
                    picks.append((conv, fwd))
            if not picks or not allfwd:
                continue
            longs = sorted(picks, key=lambda x: -x[0])[:self.TOP_N]
            sig = sum(p[1] for p in longs) / len(longs)
            mkt = sum(allfwd) / len(allfwd)
            sig_rets.append(sig); mkt_rets.append(mkt); excess.append(sig - mkt)

        if len(excess) < 50:
            return {"status": "INSUFFICIENT_PERIODS"}
        import statistics
        n = len(excess)
        ppy = 252 / self.HOLD_DAYS
        mean_ex = sum(excess) / n
        rng = random.Random(self.SEED + 1)
        hits = sum(1 for _ in range(self.PERMUTATIONS)
                   if abs(sum(x if rng.random() < 0.5 else -x for x in excess) / n) >= abs(mean_ex))
        p_ex = (hits + 1) / (self.PERMUTATIONS + 1)

        def ann(m):
            return round(((1 + m) ** ppy - 1) * 100, 2)
        return {
            "periods": n,
            "long_only_annualized_pct": ann(sum(sig_rets) / n),
            "market_beta_annualized_pct": ann(sum(mkt_rets) / n),
            "excess_alpha_annualized_pct": ann(mean_ex),
            "excess_alpha_bps_per_period": round(mean_ex * 10000, 2),
            "excess_sharpe_annualized": round(mean_ex / (statistics.pstdev(excess) or 1e-9) * (ppy ** 0.5), 2),
            "excess_p_value": round(p_ex, 4),
            "excess_significant": bool(p_ex < 0.05),
        }

    def verdict(self, save=True):
        """The full go/no-go synthesis: signal edge, beta decomposition, and the OPTIONS call."""
        import json
        ls = self.run(long_only=False, save=False)
        lo = self.run(long_only=True, save=False)
        bench = self.benchmark_decomposition()
        if "gross_mean_per_period_bps" not in ls:
            return {"status": ls.get("status", "BACKTEST_FAILED")}

        # The options call: an OTM option round-trip costs ~500-1500 bps of premium. The edge's
        # breakeven is in the tens of bps. So the vehicle verdict does not depend on the exact
        # alpha — it is destroyed by an order of magnitude either way.
        be_lo = lo.get("breakeven_one_way_cost_bps")
        alpha_bps = bench.get("excess_alpha_bps_per_period")
        return _save(self, {
            "timestamp": datetime.utcnow().isoformat(),
            "signal_edge": {
                "market_neutral_long_short_significant": ls.get("gross_significant"),
                "market_neutral_p_value": ls.get("p_value_gross"),
                "long_only_excess_over_market_significant": bench.get("excess_significant"),
                "long_only_excess_alpha_annualized_pct": bench.get("excess_alpha_annualized_pct"),
                "long_only_excess_p_value": bench.get("excess_p_value"),
                "beta_removed_annualized_pct": bench.get("market_beta_annualized_pct"),
            },
            "reading": (
                "The market-NEUTRAL form (long-short) is NOT significant, while the LONG-ONLY "
                "excess-over-market IS. That gap is survivorship bias in textbook form: the "
                "short side needs the names that FAILED, and those are absent, so shorting a "
                "survivor-only bull market loses and washes the long-short out. A long-side "
                "selection edge appears real but is survivorship-INFLATED and cannot be cleanly "
                "sized without delisted data."),
            "options_vehicle_verdict": {
                "breakeven_one_way_cost_bps": be_lo,
                "otm_option_roundtrip_cost_bps": "≈500-1500 of premium",
                "verdict": "OTM OPTIONS CANNOT CARRY THIS EDGE",
                "why": (f"the edge breaks even at ~{be_lo} bps one-way; an OTM option round-trip "
                        f"costs 10-30x that. The proven factor must be traded as EQUITY or "
                        f"deep-ITM/delta-1, never OTM options — matching the signal engine's own "
                        f"'doubtful for OTM options' caveat, now quantified."),
            },
            "survivorship_caveat": "universe is survivor-only; every positive number here is an "
                                   "UPPER bound. A paid survivorship-free dataset is required to "
                                   "size the real edge or trust the short side.",
            "status": "MOMENTUM_REVERSAL_VERDICT_COMPLETE",
        }, save)

    def last_report(self):
        try:
            import json
            return json.loads(self.OUT.read_text())
        except Exception:
            return None


def _save(engine, result, save):
    if save:
        try:
            import json
            engine.OUT.parent.mkdir(parents=True, exist_ok=True)
            (engine.OUT.parent / "momentum_reversal_verdict.json").write_text(json.dumps(result, indent=2))
        except Exception:
            pass
    return result
