"""
Fork 1 validation — is the signal a real strategy when traded as EQUITY, net of cost?

A thin per-trade edge (balanced acc 0.514, ~0.23%/5d) is only usable if a DIVERSIFIED
basket of such bets each period cancels the idiosyncratic noise and leaves the small
mean edge as a respectable risk-adjusted return. This runs exactly that, using the
real DirectionalSignalEngine we would ship:

  each period (non-overlapping 5 trading days):
    - for every symbol firing CONFIRMED, take +1 (bullish) or -1 (bearish) the underlying
    - equal-weight the basket, hold 5 days, realize the underlying return minus cost
  build the period-return series -> annualized return, Sharpe, drawdown, train/test.

Decision-grade output: if net-of-cost Sharpe isn't clearly positive AND consistent
out of sample, fork 1 does not get wired to live trading.
"""
import csv
import glob
import math
import os

from app.services.directional_signal_engine import DirectionalSignalEngine

HORIZON = 5
PERIODS_PER_YEAR = 252 / HORIZON
SPLIT = "2015-01-01"
COST_BPS = [0, 5, 10]     # round-trip cost per position, basis points
MIN_BARS = 253


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


def stats(period_returns, cost_frac):
    """period_returns: list of (date, [per_position_gross_returns_fraction])."""
    net = []
    for d, rs in period_returns:
        if not rs:
            continue
        pnl = sum(r - cost_frac for r in rs) / len(rs)   # equal-weight, cost per position
        net.append((d, pnl))
    if len(net) < 10:
        return None
    xs = [p for _, p in net]
    n = len(xs)
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    std = math.sqrt(var)
    sharpe = (mean / std) * math.sqrt(PERIODS_PER_YEAR) if std else 0.0
    ann = mean * PERIODS_PER_YEAR
    # max drawdown on the cumulative (additive) curve
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for x in xs:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    winrate = 100 * sum(1 for x in xs if x > 0) / n
    return {
        "periods": n,
        "ann_return_pct": round(ann * 100, 2),
        "sharpe": round(sharpe, 2),
        "period_win_pct": round(winrate, 1),
        "max_dd_pct": round(mdd * 100, 2),
        "mean_bps": round(mean * 1e4, 1),
    }


def main():
    eng = DirectionalSignalEngine()
    csvs = sorted(glob.glob("app/data/historical/*_daily.csv"))

    series = {}
    idx = {}
    for p in csvs:
        sym = os.path.basename(p).replace("_daily.csv", "")
        s = load(p)
        series[sym] = s
        idx[sym] = {d: i for i, (d, _) in enumerate(s)}

    all_dates = sorted({d for s in series.values() for d, _ in s})
    sampled = all_dates[MIN_BARS::HORIZON]

    train, test = [], []
    long_ct = short_ct = 0
    for D in sampled:
        rets = []
        for sym, s in series.items():
            i = idx[sym].get(D)
            if i is None or i < MIN_BARS or i + HORIZON >= len(s):
                continue
            window = [c for _, c in s[i - MIN_BARS + 1:i + 1]]
            sig = eng.evaluate(window)
            if not sig.get("tradeable"):
                continue
            c0, c1 = s[i][1], s[i + HORIZON][1]
            if c0 <= 0:
                continue
            raw = c1 / c0 - 1
            sign = 1 if sig["directional_bias"] == "BULLISH" else -1
            if sign > 0:
                long_ct += 1
            else:
                short_ct += 1
            rets.append(sign * raw)
        (test if D >= SPLIT else train).append((D, rets))

    tot = long_ct + short_ct
    print("=" * 72)
    print("FORK 1: EQUITY PORTFOLIO BACKTEST  (momentum + reversal, diversified)")
    print("=" * 72)
    print(f"horizon {HORIZON}d | long positions {long_ct} ({100*long_ct/tot:.0f}%) / "
          f"short {short_ct} ({100*short_ct/tot:.0f}%)")
    print(f"avg positions/period: {tot / max(1, len(sampled)):.1f}")
    print()
    for cost in COST_BPS:
        cf = cost / 1e4
        tr, te = stats(train, cf), stats(test, cf)
        print(f"--- round-trip cost {cost} bps/position ---")
        for label, s in (("TRAIN (<2015)", tr), ("TEST  (>=2015)", te)):
            if s:
                print(f"  {label}: ann {s['ann_return_pct']:>6}%  Sharpe {s['sharpe']:>5}  "
                      f"win {s['period_win_pct']:>5}%  maxDD {s['max_dd_pct']:>6}%  "
                      f"mean {s['mean_bps']:>5}bps  (n={s['periods']})")
        print()
    print("DECISION: wire to live only if net-of-cost Sharpe is clearly > 0 AND holds in TEST.")


if __name__ == "__main__":
    main()
