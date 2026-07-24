"""Test whether MECHANICAL (forced, calendar-driven) flow leaves an exploitable price effect.

The flow hypothesis GreyLine was built on — detect informed institutional flow and follow it —
was tested and failed: no edge at 1/3/5/10 days once overlap and multiple comparisons were
corrected. That result is consistent with market structure. Informed flow is deliberately
concealed, and by the time it is visible in end-of-day aggregate data its impact is largely
priced. You are racing information you will never have.

Mechanical flow is a structurally different bet. Pension and target-date rebalancing, index
reconstitution and dealer expiry hedging move price for reasons UNRELATED to value, on dates
known in advance. You are not competing on information — you are supplying liquidity to
someone who has no choice about trading. If any flow effect is capturable at daily horizon,
this is the family where it should live.

PRE-REGISTERED HYPOTHESES (fixed before looking, so this is not a scan):

  H1 TURN_OF_MONTH        The last trading day of a month plus the first three of the next
                          differ from other days — the window when payroll/pension inflows
                          and target-weight rebalancing are mechanically executed.
  H2 REBALANCE_REVERSAL   Across that same window, the prior month's biggest LOSERS beat its
                          biggest WINNERS. Restoring target weights means selling what rose
                          and buying what fell — a directional prediction, not a direction-
                          agnostic "something happens".
  H3 POST_OPEX_DRIFT      The week after monthly option expiry differs from other weeks, as
                          the dealer gamma that pinned price into expiry rolls off.

THE TWO TRAPS THAT KILLED THE LAST HYPOTHESIS, AND HOW EACH IS HANDLED:

  Cross-sectional correlation — 557 symbols on one date are nearly one observation, not 557.
  Every test therefore collapses each date to a single cross-sectional mean and treats DATES
  (H1/H3) or MONTHS (H2) as the unit. Reporting symbol-days as n is how 3.4M rows manufacture
  a p-value out of noise.

  Multiple comparisons — three hypotheses are declared up front and every p-value is
  Bonferroni-adjusted by that count. No post-hoc selection of the horizon that happened to
  work.

Inference is a permutation test on shuffled date labels, not a t-test: daily returns are fat-
tailed and serially dependent, and the normal approximation flatters exactly the tiny effects
under examination.

Pre-listing stubs are excluded via PriceBarTradabilityEngine — SW carries 16 years of ~$180/day
prints, which are frictionless zero-volatility bars that manufacture clean fake patterns.

This engine is RESEARCH ONLY. It reads history and returns statistics. It never trades.
"""

import csv
import json
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class MechanicalFlowResearchEngine:

    HIST_DIR = Path("app/data/historical")
    OUT = Path("app/data/research/mechanical_flow_study.json")

    TOM_BEFORE = 1            # last N trading days of the month
    TOM_AFTER = 3             # first N trading days of the next
    DECILE = 0.10             # top/bottom decile for the rebalance-reversal test
    PERMUTATIONS = 10_000
    HYPOTHESES = 3            # pre-registered count -> the Bonferroni divisor
    SEED = 20260723           # fixed so the permutation p-values are reproducible

    # ---------------------------------------------------------------- data

    def _load(self, exclude_stubs=True):
        """{symbol: [(date, close)]}, clipped to the genuinely tradable era."""
        tradable_from = {}
        if exclude_stubs:
            try:
                from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
                tradable_from = PriceBarTradabilityEngine().tradable_from_map()
            except Exception:
                tradable_from = {}

        series = {}
        for p in sorted(self.HIST_DIR.glob("*_daily.csv")):
            sym = p.name.replace("_daily.csv", "")
            floor = tradable_from.get(sym)
            rows = []
            try:
                with open(p) as f:
                    for r in csv.DictReader(f):
                        try:
                            d = str(r["date"])[:10]
                            if floor and d < floor:
                                continue
                            rows.append((d, float(r["close"])))
                        except (ValueError, KeyError, TypeError):
                            continue
            except Exception:
                continue
            if len(rows) > 60:
                series[sym] = rows
        return series, tradable_from

    @staticmethod
    def _daily_returns(series):
        """{date: {symbol: return}} — simple close-to-close."""
        by_date = defaultdict(dict)
        for sym, rows in series.items():
            prev = None
            for d, c in rows:
                if prev and prev > 0 and c > 0:
                    by_date[d][sym] = c / prev - 1.0
                prev = c
        return by_date

    # ------------------------------------------------------------ calendar

    @staticmethod
    def _third_friday(year, month):
        from datetime import date, timedelta
        d = date(year, month, 1)
        fridays = 0
        while True:
            if d.weekday() == 4:
                fridays += 1
                if fridays == 3:
                    return d.isoformat()
            d += timedelta(days=1)

    def _label_dates(self, dates):
        """Tag each trading date with the mechanical-flow windows it belongs to."""
        dates = sorted(dates)
        idx = {d: i for i, d in enumerate(dates)}
        month_last = {}
        for d in dates:
            month_last[d[:7]] = d          # last trading date seen in each month

        tom, post_opex = set(), set()
        for ym, last in month_last.items():
            i = idx[last]
            for k in range(self.TOM_BEFORE):
                if i - k >= 0:
                    tom.add(dates[i - k])
            for k in range(1, self.TOM_AFTER + 1):
                if i + k < len(dates):
                    tom.add(dates[i + k])

        for ym in month_last:
            y, m = int(ym[:4]), int(ym[5:7])
            try:
                tf = self._third_friday(y, m)
            except Exception:
                continue
            # first trading date strictly after the third Friday, then the following 5 sessions
            after = [d for d in dates if d > tf]
            for d in after[:5]:
                post_opex.add(d)
        return tom, post_opex

    # ----------------------------------------------------------- inference

    def _permutation_p(self, values, labels, observed, rng):
        """Two-sided p over shuffled labels. Unit of observation = one entry in `values`."""
        n_event = sum(labels)
        if n_event == 0 or n_event == len(values):
            return 1.0
        hits = 0
        pool = list(values)
        for _ in range(self.PERMUTATIONS):
            rng.shuffle(pool)
            ev = sum(pool[:n_event]) / n_event
            ct = sum(pool[n_event:]) / (len(pool) - n_event)
            if abs(ev - ct) >= abs(observed):
                hits += 1
        return (hits + 1) / (self.PERMUTATIONS + 1)

    def _compare(self, name, per_unit, flags, rng, unit):
        ev = [v for v, f in zip(per_unit, flags) if f]
        ct = [v for v, f in zip(per_unit, flags) if not f]
        if len(ev) < 20 or len(ct) < 20:
            return {"hypothesis": name, "status": "INSUFFICIENT_DATA",
                    "event_n": len(ev), "control_n": len(ct)}
        m_ev, m_ct = sum(ev) / len(ev), sum(ct) / len(ct)
        diff = m_ev - m_ct
        p = self._permutation_p(per_unit, flags, diff, rng)
        p_adj = min(1.0, p * self.HYPOTHESES)
        return {
            "hypothesis": name,
            "unit_of_observation": unit,
            "event_n": len(ev), "control_n": len(ct),
            "event_mean_bps": round(m_ev * 10_000, 2),
            "control_mean_bps": round(m_ct * 10_000, 2),
            "difference_bps": round(diff * 10_000, 2),
            "p_value": round(p, 4),
            "p_value_bonferroni": round(p_adj, 4),
            "significant_after_correction": bool(p_adj < 0.05),
        }

    # --------------------------------------------------------------- study

    def run(self, save=True):
        rng = random.Random(self.SEED)
        series, tradable_from = self._load()
        by_date = self._daily_returns(series)
        dates = sorted(d for d, r in by_date.items() if len(r) >= 20)
        if len(dates) < 500:
            return {"status": "INSUFFICIENT_HISTORY", "dates": len(dates)}

        tom, post_opex = self._label_dates(dates)

        # H1 / H3 — one cross-sectional mean per DATE. 557 correlated symbols are ~1
        # observation, so the date is the unit; using symbol-days would inflate n ~500x.
        xs_mean = [sum(by_date[d].values()) / len(by_date[d]) for d in dates]
        h1 = self._compare("H1_TURN_OF_MONTH", xs_mean, [d in tom for d in dates],
                           rng, "trading date (cross-sectional mean)")
        h3 = self._compare("H3_POST_OPEX_DRIFT", xs_mean, [d in post_opex for d in dates],
                           rng, "trading date (cross-sectional mean)")

        # H2 — the DIRECTIONAL prediction. Rank by prior-month return, then measure
        # (losers - winners) across the turn-of-month window. Unit = MONTH, so the ~300
        # months are close to independent draws rather than overlapping windows.
        h2 = self._rebalance_reversal(series, by_date, dates, rng)

        results = [h1, h2, h3]
        surviving = [r for r in results if r.get("significant_after_correction")]
        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "MechanicalFlowResearchEngine",
            "symbols": len(series),
            "trading_dates": len(dates),
            "date_range": [dates[0], dates[-1]],
            "stubs_clipped": len(tradable_from),
            "permutations": self.PERMUTATIONS,
            "hypotheses_pre_registered": self.HYPOTHESES,
            "correction": "Bonferroni across pre-registered hypotheses",
            "results": results,
            "surviving_correction": [r["hypothesis"] for r in surviving],
            "verdict": ("NO_MECHANICAL_FLOW_EDGE_DETECTED" if not surviving
                        else "CANDIDATE_EFFECT_SURVIVES_CORRECTION"),
            "survivorship": self._survivorship_declaration(),
            "caveat": ("Surviving correction means the effect is not obviously noise. It does "
                       "NOT mean it is tradable: costs, slippage and capacity are untested "
                       "here, and a daily cross-sectional mean is not a portfolio."),
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(json.dumps(out, indent=2))
            except Exception:
                pass
        return out

    def _rebalance_reversal(self, series, by_date, dates, rng):
        idx = {d: i for i, d in enumerate(dates)}
        month_last = {}
        for d in dates:
            month_last[d[:7]] = d

        closes = {s: dict(rows) for s, rows in series.items()}
        months = sorted(month_last)
        spreads = []
        for k in range(1, len(months)):
            prev_end, this_end = month_last[months[k - 1]], month_last[months[k]]
            i = idx[this_end]
            window = [dates[j] for j in range(i - self.TOM_BEFORE + 1,
                                              min(i + self.TOM_AFTER + 1, len(dates)))]
            if len(window) < self.TOM_BEFORE + self.TOM_AFTER:
                continue

            # Rank on data STRICTLY BEFORE the window opens.
            #
            # The first version ranked on the return through `this_end` while the window also
            # STARTED at `this_end`. A stock that jumped on the last day was labelled a winner
            # BECAUSE of that day, and the same day was then counted in its window return —
            # guaranteed double-counting. It produced a hugely "significant" -149bps result
            # (p=0.0001) that was pure overlap, the exact trap that killed the flow study.
            rank_i = i - self.TOM_BEFORE          # last bar before the window opens
            if rank_i <= 0:
                continue
            rank_end = dates[rank_i]
            prior = {}
            for s, cl in closes.items():
                a, b = cl.get(prev_end), cl.get(rank_end)
                if a and b and a > 0:
                    prior[s] = b / a - 1.0
            if len(prior) < 50:
                continue
            ranked = sorted(prior, key=prior.get)
            cut = max(1, int(len(ranked) * self.DECILE))
            losers, winners = ranked[:cut], ranked[-cut:]

            def window_ret(group):
                tot, n = 0.0, 0
                for s in group:
                    r = 1.0
                    ok = False
                    for d in window:
                        v = by_date.get(d, {}).get(s)
                        if v is not None:
                            r *= (1 + v); ok = True
                    if ok:
                        tot += r - 1.0; n += 1
                return tot / n if n else None

            lw, ww = window_ret(losers), window_ret(winners)
            if lw is None or ww is None:
                continue
            spreads.append(lw - ww)      # positive = losers beat winners, as predicted

        if len(spreads) < 40:
            return {"hypothesis": "H2_REBALANCE_REVERSAL", "status": "INSUFFICIENT_DATA",
                    "months": len(spreads)}

        mean = sum(spreads) / len(spreads)
        # Sign-flip permutation: under the null the spread is symmetric about zero, so
        # randomising each month's SIGN is the natural null for a directional prediction.
        hits = 0
        for _ in range(self.PERMUTATIONS):
            tot = sum(x if rng.random() < 0.5 else -x for x in spreads)
            if abs(tot / len(spreads)) >= abs(mean):
                hits += 1
        p = (hits + 1) / (self.PERMUTATIONS + 1)
        p_adj = min(1.0, p * self.HYPOTHESES)
        wins = sum(1 for x in spreads if x > 0)
        return {
            "hypothesis": "H2_REBALANCE_REVERSAL",
            "unit_of_observation": "month (loser decile - winner decile over the TOM window)",
            "months": len(spreads),
            "mean_spread_bps": round(mean * 10_000, 2),
            "months_positive": wins,
            "hit_rate": round(wins / len(spreads), 3),
            "p_value": round(p, 4),
            "p_value_bonferroni": round(p_adj, 4),
            "significant_after_correction": bool(p_adj < 0.05),
            "direction_as_predicted": bool(mean > 0),
        }

    def _survivorship_declaration(self):
        """State the bias rather than leaving the reader to assume it away.

        A study on a universe containing only survivors is biased UPWARD. That matters
        asymmetrically: a null result (like this one) is conservative and therefore more
        trustworthy, while a POSITIVE result could be the bias itself. Any future hypothesis
        that shows promise on this data must be read against this field.
        """
        try:
            from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine
            st = UniverseSurvivorshipEngine().status()
        except Exception:
            return {"survivorship_free": False, "detail": "status unavailable"}
        mag = None
        try:
            from app.services.survivorship_bias_engine import SurvivorshipBiasEngine
            mag = SurvivorshipBiasEngine().headline()
        except Exception:
            mag = None
        return {
            "survivorship_free": False,
            "survivorship_free_from": st.get("survivorship_free_from"),
            "retained_delisted_count": st.get("retained_delisted_count"),
            "measured_disappearance": mag,
            "effect_on_inference": ("Universe excludes companies that failed, so results are "
                                    "biased UPWARD. A null is conservative; a positive finding "
                                    "may be an artifact of surviving-winners selection."),
        }

    def last_study(self):
        try:
            return json.loads(self.OUT.read_text())
        except Exception:
            return None
