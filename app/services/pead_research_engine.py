"""Post-Earnings Announcement Drift — a PRE-REGISTERED test of the best-supported anomaly we
have data for.

Why this hypothesis and not another: PEAD has been documented since Ball & Brown (1968) and has
survived six decades of out-of-sample scrutiny, unlike the two flow hypotheses this system
already tested and falsified. Crucially it is also the first candidate whose ARITHMETIC does
not immediately disqualify options — published drift for extreme surprise deciles runs a few
percent over 1-2 months, roughly 10-20x the momentum-reversal edge that OTM option costs
destroyed.

PRE-REGISTERED, fixed before looking:
  H1  Stocks with the most POSITIVE earnings surprise outperform those with the most NEGATIVE
      surprise over the weeks following the announcement, measured as a long-short spread.
  Primary horizon 40 trading days; 20 and 60 reported as secondary. Three horizons -> every
  p-value Bonferroni-adjusted by 3. No post-hoc horizon selection.

THE TRAPS, AND HOW EACH IS HANDLED (every one of these has bitten this repo already):

  ANNOUNCEMENT JUMP IS NOT THE EDGE. The price gap on the announcement is not capturable — by
  the time the number is public it is in the price. Entry is therefore deferred to the close
  ENTRY_LAG_DAYS after the report date, which clears the reaction regardless of whether the
  release was before the open or after the close. We deliberately forfeit the jump and measure
  only the DRIFT that follows.

  LOOK-AHEAD. The surprise is known at announcement; the forward window begins strictly after
  entry. Ranking never touches the measurement window — the exact overlap bug that faked a
  149bps "mechanical flow" edge.

  CROSS-SECTIONAL CORRELATION. Earnings cluster in seasons; two events in the same week share
  market-wide moves and are nowhere near independent. So events are grouped into monthly
  COHORTS, one long-short spread per cohort, and the cohort is the unit of inference. Treating
  each event as independent would inflate n by ~100x and manufacture significance.

  MARKET MOVE. Each event's return is measured ABNORMAL — stock return minus the equal-weight
  universe return over the identical window — so a rising market is not mistaken for drift.

  SURVIVORSHIP. The universe holds only survivors, biasing any positive result UPWARD. A null
  here is conservative; a positive is an upper bound.

Inference is a sign-flip permutation test on cohort spreads, not a t-test: the spread series is
fat-tailed and small-n, where the normal approximation flatters exactly the effects in question.
"""

import csv
import json
import random
import statistics
from datetime import datetime
from pathlib import Path


class PEADResearchEngine:

    TR_DIR = Path("app/data/historical_total_return")
    RAW_DIR = Path("app/data/historical")
    EARN_DIR = Path("app/data/earnings")
    OUT = Path("app/data/research/pead_study.json")

    ENTRY_LAG_DAYS = 2         # clears the announcement reaction (BMO or AMC) before entry
    HORIZONS = (20, 40, 60)    # pre-registered; 40 is primary
    PRIMARY_HORIZON = 40
    DECILE = 0.20              # top/bottom quintile by surprise
    MIN_EVENTS_PER_COHORT = 10
    PERMUTATIONS = 5000
    SEED = 20260724

    # ---------------------------------------------------------------- data

    def _load_prices(self):
        """{symbol: {date: adj_close}} — total return where available, raw close otherwise."""
        series = {}
        for p in self.TR_DIR.glob("*_total_return.csv"):
            sym = p.name.replace("_total_return.csv", "")
            row = {}
            try:
                with open(p) as f:
                    for r in csv.DictReader(f):
                        try:
                            row[str(r["date"])[:10]] = float(r["adj_close"])
                        except (ValueError, KeyError, TypeError):
                            continue
            except Exception:
                continue
            if len(row) > 100:
                series[sym] = row
        return series

    def _load_events(self):
        """(symbol, report_date, surprise_pct) for every historical announcement we have."""
        events = []
        for p in self.EARN_DIR.glob("*.json"):
            sym = p.stem
            try:
                rows = json.loads(p.read_text())
            except Exception:
                continue
            for r in rows or []:
                d = str(r.get("report_date") or "")[:10]
                sp = r.get("surprise_percentage")
                if not d or sp in (None, ""):
                    continue
                try:
                    sp = float(sp)
                except (TypeError, ValueError):
                    continue
                # guard against absurd reported values (data errors, tiny-EPS blowups)
                if abs(sp) > 1000:
                    continue
                events.append((sym, d, sp))
        return events

    # ----------------------------------------------------------- inference

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

    # --------------------------------------------------------------- study

    def run(self, save=True):
        prices = self._load_prices()
        events = self._load_events()
        if len(prices) < 50 or len(events) < 500:
            return {"status": "INSUFFICIENT_DATA", "symbols": len(prices), "events": len(events)}

        # common calendar + per-symbol index for O(1) forward lookups
        all_dates = sorted({d for row in prices.values() for d in row})
        idx_of = {d: i for i, d in enumerate(all_dates)}
        aligned = {s: [row.get(d) for d in all_dates] for s, row in prices.items()}

        # equal-weight universe return per window is the benchmark (abnormal return)
        def fwd_return(sym, i0, i1):
            c = aligned.get(sym)
            if c is None or i1 >= len(c):
                return None
            a, b = c[i0], c[i1]
            if not a or not b or a <= 0:
                return None
            return b / a - 1.0

        rng = random.Random(self.SEED)
        results = {}
        for H in self.HORIZONS:
            # collect abnormal returns per event
            per_event = []          # (cohort, surprise, abnormal_return)
            for sym, rdate, sp in events:
                i = idx_of.get(rdate)
                if i is None:                      # report date not a trading day in our calendar
                    nxt = [d for d in all_dates if d > rdate]
                    if not nxt:
                        continue
                    i = idx_of[nxt[0]]
                i0 = i + self.ENTRY_LAG_DAYS       # entry AFTER the announcement reaction
                i1 = i0 + H
                if i1 >= len(all_dates):
                    continue
                r = fwd_return(sym, i0, i1)
                if r is None:
                    continue
                per_event.append((all_dates[i0][:7], sp, r, i0, i1))

            if len(per_event) < 500:
                results[H] = {"status": "INSUFFICIENT_EVENTS", "events": len(per_event)}
                continue

            # market benchmark per (i0,i1) window, computed once per distinct window
            wins = {}
            for _, _, _, i0, i1 in per_event:
                wins.setdefault((i0, i1), None)
            for (i0, i1) in list(wins):
                rs = []
                for c in aligned.values():
                    if i1 < len(c):
                        a, b = c[i0], c[i1]
                        if a and b and a > 0:
                            rs.append(b / a - 1.0)
                wins[(i0, i1)] = (sum(rs) / len(rs)) if len(rs) >= 20 else None

            # cohort spreads: top-quintile surprise minus bottom-quintile, ABNORMAL
            by_cohort = {}
            for cohort, sp, r, i0, i1 in per_event:
                mkt = wins.get((i0, i1))
                if mkt is None:
                    continue
                by_cohort.setdefault(cohort, []).append((sp, r - mkt))

            spreads, n_events = [], 0
            for cohort, rows in sorted(by_cohort.items()):
                if len(rows) < self.MIN_EVENTS_PER_COHORT:
                    continue
                rows.sort(key=lambda x: x[0])
                k = max(1, int(len(rows) * self.DECILE))
                lo = sum(x[1] for x in rows[:k]) / k          # most negative surprise
                hi = sum(x[1] for x in rows[-k:]) / k         # most positive surprise
                spreads.append(hi - lo)
                n_events += len(rows)

            if len(spreads) < 20:
                results[H] = {"status": "INSUFFICIENT_COHORTS", "cohorts": len(spreads)}
                continue

            mean = sum(spreads) / len(spreads)
            p = self._sign_flip_p(spreads, mean, rng, self.PERMUTATIONS)
            p_adj = min(1.0, p * len(self.HORIZONS))
            sd = statistics.pstdev(spreads) or 1e-9
            results[H] = {
                "horizon_days": H,
                "cohorts": len(spreads), "events": n_events,
                "mean_spread_pct": round(mean * 100, 3),
                "hit_rate": round(sum(1 for s in spreads if s > 0) / len(spreads), 3),
                "spread_sharpe_per_cohort": round(mean / sd, 3),
                "p_value": round(p, 4),
                "p_value_bonferroni": round(p_adj, 4),
                "significant_after_correction": bool(p_adj < 0.05),
            }

        primary = results.get(self.PRIMARY_HORIZON, {})
        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PEADResearchEngine",
            "hypothesis": ("PRE-REGISTERED H1: most-positive earnings surprises outperform "
                           "most-negative over the following weeks (long-short spread). "
                           "Primary horizon 40d; 20d/60d secondary; Bonferroni by 3."),
            "design": {
                "entry": f"close {self.ENTRY_LAG_DAYS} trading days after report date — the "
                         f"announcement jump is deliberately forfeited, only DRIFT is measured",
                "return": "ABNORMAL (stock minus equal-weight universe over the same window)",
                "unit_of_inference": "monthly cohort spread (earnings cluster; events are NOT "
                                     "independent)",
                "inference": "sign-flip permutation on cohort spreads",
                "input": "total-return adjusted closes",
            },
            "symbols_with_prices": len(prices),
            "earnings_events_loaded": len(events),
            "results_by_horizon": results,
            "primary": primary,
            "survivorship": {"survivorship_free": False,
                             "effect": "universe holds only survivors -> any positive result is "
                                       "an UPPER bound; a null is conservative"},
            "verdict": ("PEAD_DETECTED" if primary.get("significant_after_correction")
                        else "NO_PEAD_EDGE_DETECTED"),
            "status": "PEAD_STUDY_COMPLETE",
        }
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
