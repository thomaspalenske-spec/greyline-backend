"""
Cross-sectional SELECTION test — does GreyLine's ranking pick winners?

The first backtest graded individual calls. But the live system does something
different: each day it scores the whole universe and trades the TOP-ranked
candidate. This tests that behavior directly.

Question: does the top-K-by-composite basket beat (a) the average of all the
signal's own calls that day (selection skill), and (b) just holding the universe
(does the strategy beat buy-everything)? If picking the highest score is no better
than picking at random from the calls, the ranking carries no information.

Same discipline: fixed forward horizon, non-overlapping periods, own scorer.
"""
import csv
import glob
import os
from collections import defaultdict

from app.services.simulation.historical_opportunity_scoring_engine import (
    HistoricalOpportunityScoringEngine,
)

HORIZON = 5
MIN_HISTORY = 30
TOP_K = [1, 3, 5]


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["date"][:10], float(r["close"])))
            except (ValueError, KeyError, TypeError):
                pass
    rows.sort()
    return rows


def main():
    eng = HistoricalOpportunityScoringEngine()
    csvs = sorted(glob.glob("app/data/historical/*_daily.csv"))

    series = {}       # sym -> list[(date, close)]
    idx = {}          # sym -> {date: i}
    for p in csvs:
        sym = os.path.basename(p).replace("_daily.csv", "")
        s = load(p)
        series[sym] = s
        idx[sym] = {d: i for i, (d, _) in enumerate(s)}

    all_dates = sorted({d for s in series.values() for d, _ in s})
    sampled = all_dates[MIN_HISTORY::HORIZON]

    # per-period: strategy return for each K, all-calls mean, universe mean
    picks_ret = {k: [] for k in TOP_K}
    allcalls_ret = []
    universe_ret = []
    periods = 0

    for D in sampled:
        candidates = []      # (composite, directional_ret)
        uni = []             # raw fwd returns of every symbol trading that day
        for sym, s in series.items():
            i = idx[sym].get(D)
            if i is None or i < MIN_HISTORY or i + HORIZON >= len(s):
                continue
            c0 = s[i][1]
            c1 = s[i + HORIZON][1]
            if c0 <= 0:
                continue
            raw = (c1 / c0 - 1) * 100
            uni.append(raw)

            opp = eng.score_snapshot(sym, D).get("opportunity") or {}
            if not opp.get("candidate_available"):
                continue
            bias = opp.get("directional_bias")
            if bias not in ("BULLISH", "BEARISH"):
                continue
            dir_ret = raw if bias == "BULLISH" else -raw
            candidates.append((float(opp.get("composite_score") or 0), dir_ret))

        if len(candidates) < max(TOP_K) or not uni:
            continue
        periods += 1
        candidates.sort(key=lambda x: x[0], reverse=True)
        for k in TOP_K:
            picks_ret[k].append(sum(d for _, d in candidates[:k]) / k)
        allcalls_ret.append(sum(d for _, d in candidates) / len(candidates))
        universe_ret.append(sum(uni) / len(uni))

    def stat(xs):
        n = len(xs)
        if not n:
            return (0, 0, 0)
        mean = sum(xs) / n
        winrate = 100 * sum(1 for x in xs if x > 0) / n
        return (round(mean, 3), round(winrate, 1), n)

    print("=" * 70)
    print("CROSS-SECTIONAL SELECTION TEST  (does ranking pick winners?)")
    print("=" * 70)
    print(f"horizon {HORIZON}d, non-overlapping | periods: {periods}")
    print(f"(each number is per-period directional return %, held {HORIZON} days)")
    print()
    am, aw, an = stat(allcalls_ret)
    um, uw, un = stat(universe_ret)
    print(f"  {'basket':>16} {'mean_ret%':>10} {'periods_up%':>12}")
    for k in TOP_K:
        m, w, n = stat(picks_ret[k])
        print(f"  {'TOP-' + str(k):>16} {m:>10} {w:>12}")
    print(f"  {'ALL calls (avg)':>16} {am:>10} {aw:>12}   <- selection benchmark")
    print(f"  {'universe (raw)':>16} {um:>10} {uw:>12}   <- buy-everything benchmark")
    print()
    top1m = stat(picks_ret[1])[0]
    print("READ:")
    print(f"  Selection skill = does TOP-1 ({top1m}) beat ALL-calls avg ({am})?")
    print(f"  Directional edge = is TOP-1 mean ({top1m}) reliably > 0 with periods_up% >> 50?")
    print("  If TOP-K ~= ALL-calls and periods_up% ~= 50, the ranking selects nothing.")


if __name__ == "__main__":
    main()
