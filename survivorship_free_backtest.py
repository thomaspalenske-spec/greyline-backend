"""Fork 1 re-validation against the survivorship-free 2013+ universe.

equity_portfolio_backtest.py answers the same question against the 98 hand-picked names in
app/data/historical — companies chosen in June 2026 because they were worth choosing, none
of which failed. This runs the same signal against every US common stock that was actually
tradable on each rebalance date, roughly 40% of which have since delisted.

Four things this does that the original could not:

1. POINT-IN-TIME UNIVERSE. Membership is resolved per rebalance date from ipo_date and
   delisting_date, so a company is present exactly while it was listed. The original's
   directory glob is nearly equivalent once delisted CSVs exist (a dead name simply has no
   bars), but resolving explicitly is what makes the claim auditable rather than incidental.

2. DELISTING RETURNS ARE REALIZED, NOT SKIPPED. The original skips any position without a
   full 5 more bars (`i + HORIZON >= len(s)`). For a company about to be delisted that
   silently discards its FINAL period — usually the catastrophic one. Here, if a symbol
   delists inside the horizon the return is taken to its last traded price. Running out of
   bars because the DATASET ends is different and is still skipped; delisting_date is what
   distinguishes them.

3. LIQUIDITY GATE. A universe of ~10.8k names is mostly microcaps that a $10k account could
   not fill and whose prices are noise. Names are gated on trailing dollar volume and price
   computed strictly from bars at or before D — no lookahead.

4. ADJUSTED CLOSES. Splits and dividends make raw closes lie about returns. Signals and
   returns use adj_close; the liquidity gate uses raw close x volume, which is what actually
   traded.

Selection mirrors the live engine: conviction = percentile rank of |momentum| + percentile
rank of |reversal|, take TOP_N. Measuring a 5,000-name basket would answer a question we do
not trade.

Usage:  PYTHONPATH=. python survivorship_free_backtest.py [--top-n 10] [--min-dollar-volume 5e6]
"""

import csv
import glob
import math
import os
import statistics
import sys
from bisect import bisect_right

from app.services.directional_signal_engine import DirectionalSignalEngine
from app.services.research.point_in_time_universe_engine import PointInTimeUniverseEngine

PRICE_DIR = "app/data/research/prices"
HORIZON = 5
PERIODS_PER_YEAR = 252 / HORIZON
MIN_BARS = 253
START = "2013-01-02"          # the earliest date UW coverage is survivorship-free
SPLIT = "2020-01-01"          # train 2013-2019, test 2020-2026 (covid + 2022 bear)
COST_BPS = [0, 5, 10]
MIN_PRICE = 5.0               # penny stocks: spreads make the measured edge fiction
ADV_WINDOW = 20


def load(path):
    """(date, adj_close, dollar_volume) oldest->newest."""
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                d = r["date"][:10]
                adj = float(r["adj_close"])
                dv = float(r["close"]) * float(r["volume"])
                if adj > 0:
                    rows.append((d, adj, dv))
            except (ValueError, KeyError, TypeError):
                pass
    rows.sort()
    return rows


def stats(period_returns, cost_frac):
    net = []
    for d, rs in period_returns:
        if not rs:
            continue
        net.append((d, sum(r - cost_frac for r in rs) / len(rs)))
    if len(net) < 10:
        return None
    xs = [p for _, p in net]
    n = len(xs)
    mean = sum(xs) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    cum = peak = mdd = 0.0
    for x in xs:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return {"periods": n, "ann_return_pct": round(mean * PERIODS_PER_YEAR * 100, 2),
            "sharpe": round((mean / std) * math.sqrt(PERIODS_PER_YEAR) if std else 0.0, 2),
            "period_win_pct": round(100 * sum(1 for x in xs if x > 0) / n, 1),
            "max_dd_pct": round(mdd * 100, 2), "mean_bps": round(mean * 1e4, 1)}


def conviction_ranks(candidates):
    """Percentile rank of |momentum| + |reversal|, matching MomentumReversalStrategyEngine."""
    if not candidates:
        return
    moms = sorted(abs(c["mom"]) for c in candidates)
    revs = sorted(abs(c["rev"]) for c in candidates)
    n = len(candidates)
    for c in candidates:
        c["conviction"] = (bisect_right(moms, abs(c["mom"])) / n
                           + bisect_right(revs, abs(c["rev"])) / n)


def main():
    argv = sys.argv
    top_n = int(argv[argv.index("--top-n") + 1]) if "--top-n" in argv else 10
    min_dv = float(argv[argv.index("--min-dollar-volume") + 1]) if "--min-dollar-volume" in argv else 5e6

    eng = DirectionalSignalEngine()
    universe_engine = PointInTimeUniverseEngine()

    paths = sorted(glob.glob(f"{PRICE_DIR}/*_daily.csv"))
    if not paths:
        raise SystemExit(f"no price data in {PRICE_DIR} — run app/scripts/download_research_price_history.py")

    series, idx, delisting = {}, {}, {}
    for row in universe_engine._listings():
        d = universe_engine._date(row.get("delisting_date"))
        if d and row.get("ticker"):
            delisting[row["ticker"]] = d

    for p in paths:
        sym = os.path.basename(p).replace("_daily.csv", "")
        s = load(p)
        if len(s) >= MIN_BARS:
            series[sym] = s
            idx[sym] = {d: i for i, (d, _, _) in enumerate(s)}

    all_dates = sorted({d for s in series.values() for d, _, _ in s})
    sampled = [d for d in all_dates[::HORIZON] if d >= START]

    train, test = [], []
    long_ct = short_ct = 0
    delisting_exits = 0
    universe_sizes, eligible_sizes = [], []

    for D in sampled:
        try:
            tradable = set(universe_engine.resolve(D))
        except ValueError:
            continue
        universe_sizes.append(len(tradable))

        candidates = []
        for sym in tradable:
            s = series.get(sym)
            if s is None:
                continue
            i = idx[sym].get(D)
            if i is None or i < MIN_BARS:
                continue

            # Liquidity, computed only from bars at or before D.
            window = s[i - ADV_WINDOW + 1:i + 1]
            if len(window) < ADV_WINDOW:
                continue
            if statistics.median(dv for _, _, dv in window) < min_dv:
                continue
            if s[i][1] < MIN_PRICE:
                continue

            sig = eng.evaluate([c for _, c, _ in s[i - MIN_BARS + 1:i + 1]])
            if not sig.get("tradeable"):
                continue

            # Exit price: the bar HORIZON ahead, or — if the company delisted inside the
            # horizon — its last traded price. Skipping the latter is what hides failures.
            if i + HORIZON < len(s):
                exit_px = s[i + HORIZON][1]
            elif delisting.get(sym) and delisting[sym] <= all_dates[-1]:
                exit_px = s[-1][1]
                delisting_exits += 1
            else:
                continue        # dataset simply ends here — not a delisting

            candidates.append({"sym": sym, "mom": sig.get("momentum_12_1_pct", 0.0),
                               "rev": sig.get("reversal_5d_move_pct", 0.0),
                               "sign": 1 if sig["directional_bias"] == "BULLISH" else -1,
                               "ret": exit_px / s[i][1] - 1})

        eligible_sizes.append(len(candidates))
        conviction_ranks(candidates)
        candidates.sort(key=lambda c: c["conviction"], reverse=True)
        picked = candidates[:top_n]

        rets = []
        for c in picked:
            long_ct += c["sign"] > 0
            short_ct += c["sign"] < 0
            rets.append(c["sign"] * c["ret"])
        (test if D >= SPLIT else train).append((D, rets))

    tot = max(1, long_ct + short_ct)
    print("=" * 78)
    print("FORK 1 RE-VALIDATION — SURVIVORSHIP-FREE UNIVERSE (2013+)")
    print("=" * 78)
    print(f"price files {len(series)} | rebalances {len(sampled)} | top_n {top_n} | "
          f"min $vol {min_dv:,.0f} | min price ${MIN_PRICE}")
    if universe_sizes:
        print(f"tradable universe/date: avg {sum(universe_sizes)/len(universe_sizes):.0f} | "
              f"passing liquidity+signal: avg {sum(eligible_sizes)/len(eligible_sizes):.0f}")
    print(f"positions: long {long_ct} ({100*long_ct/tot:.0f}%) / short {short_ct} ({100*short_ct/tot:.0f}%)")
    print(f"positions exited at a DELISTING price (would have been silently dropped): {delisting_exits}")
    print()
    for cost in COST_BPS:
        cf = cost / 1e4
        tr, te = stats(train, cf), stats(test, cf)
        print(f"--- round-trip cost {cost} bps/position ---")
        for label, s in ((f"TRAIN (<{SPLIT[:4]})", tr), (f"TEST  (>={SPLIT[:4]})", te)):
            if s:
                print(f"  {label}: ann {s['ann_return_pct']:>7}%  Sharpe {s['sharpe']:>5}  "
                      f"win {s['period_win_pct']:>5}%  maxDD {s['max_dd_pct']:>7}%  "
                      f"mean {s['mean_bps']:>6}bps  (n={s['periods']})")
            else:
                print(f"  {label}: insufficient periods")
        print()
    print("Compare against equity_portfolio_backtest.py (98 survivors). A materially worse")
    print("result here is the honest number — the difference is the survivorship bias.")


if __name__ == "__main__":
    main()
