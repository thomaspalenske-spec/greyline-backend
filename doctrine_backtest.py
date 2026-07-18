"""
Validation gate for stages 3 & 4 (COA 1): does the limit-entry + trailing-stop + 4-TP
doctrine ADD value over a plain hold, on the momentum-reversal signal?

Paired comparison on the SAME signals. Event-driven, bar-by-bar on daily OHLC:
  * Entry: limit a 0.25-ATR pullback better than the signal close; fills only if the next
    bar trades through it (else the trade is SKIPPED — a real cost of limit orders).
  * Manage: 1.5-ATR initial stop, TPs at 1/2/3/4 R, scale out 25% each, stop trails up the
    ladder. Gap-aware fills; conservative (stop checked before TP within a bar).
  * Baseline: same signal, plain 5-day close-to-close hold.

If the ladder/stop destroys the thin momentum edge (exits often do), we learn it here,
before wiring any of it live. Net of 10bps round-trip. Train/test split.
"""
import csv
import glob
import math
import os

from app.services.directional_signal_engine import DirectionalSignalEngine
from app.services.trade_doctrine_engine import TradeDoctrineEngine

STEP = 5
ATR_N = 14
MAX_HOLD = 20
COST_RT_PCT = 0.10      # 10 bps round trip (turnover-based; laddering adds no bps cost)
SPLIT = "2015-01-01"
MIN_HISTORY = 253


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r["date"][:10], float(r["open"]), float(r["high"]),
                             float(r["low"]), float(r["close"])))
            except (ValueError, KeyError, TypeError):
                pass
    rows.sort()
    return rows


def atr_series(bars):
    trs = [0.0]
    for i in range(1, len(bars)):
        _, o, h, l, c = bars[i]
        pc = bars[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr, out = 0.0, [0.0] * len(bars)
    for i in range(len(bars)):
        if i < ATR_N:
            atr = sum(trs[1:i + 1]) / i if i else 0.0
        else:
            atr = (atr * (ATR_N - 1) + trs[i]) / ATR_N
        out[i] = atr
    return out


def sim_doctrine(bars, start, sign, entry, plan, doc):
    """Return net% for the COA-1 lifecycle from bar `start`, or None."""
    remaining, tps, realized, stop = 1.0, 0, 0.0, plan["initial_stop"]
    targets = plan["targets"]
    end = min(start + MAX_HOLD, len(bars))
    for j in range(start, end):
        _, o, h, l, c = bars[j]
        # stop first (conservative). gap-aware.
        if sign > 0:
            hit, fill = (l <= stop), (o if o <= stop else stop)
        else:
            hit, fill = (h >= stop), (o if o >= stop else stop)
        if hit:
            realized += remaining * (fill / entry - 1) * 100 * sign
            return realized - COST_RT_PCT
        while tps < 4:
            tp = targets[tps]
            if sign > 0:
                thit, tfill = (h >= tp), (o if o >= tp else tp)
            else:
                thit, tfill = (l <= tp), (o if o <= tp else tp)
            if not thit:
                break
            frac = min(plan["scale_out"][tps], remaining)
            realized += frac * (tfill / entry - 1) * 100 * sign
            remaining -= frac
            tps += 1
            stop = doc.trailing_stop_after(plan, tps)
            if remaining <= 1e-9:
                return realized - COST_RT_PCT
    if remaining > 1e-9:
        realized += remaining * (bars[end - 1][4] / entry - 1) * 100 * sign
    return realized - COST_RT_PCT


def stats(xs):
    n = len(xs)
    if n < 10:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) or 1e-9
    return {"n": n, "mean": round(m, 3), "sharpe_per_trade": round(m / sd, 3),
            "win_pct": round(100 * sum(1 for x in xs if x > 0) / n, 1)}


def main():
    sig, doc = DirectionalSignalEngine(), TradeDoctrineEngine()
    base = {"train": [], "test": []}
    coa1 = {"train": [], "test": []}
    signals = fills = 0

    for p in sorted(glob.glob("app/data/historical/*_daily.csv")):
        bars = load(p)
        closes = [b[4] for b in bars]
        atr = atr_series(bars)
        n = len(bars)
        for i in range(MIN_HISTORY, n - MAX_HOLD - 2, STEP):
            s = sig.evaluate(closes[:i + 1])
            if not s.get("tradeable"):
                continue
            bias = s["directional_bias"]
            sign = 1 if bias == "BULLISH" else -1
            a = atr[i]
            if a <= 0 or closes[i] <= 0:
                continue
            bucket = "test" if bars[i][0] >= SPLIT else "train"
            signals += 1

            # baseline: plain 5-day hold at close[i]
            base_ret = (closes[i + STEP] / closes[i] - 1) * 100 * sign - COST_RT_PCT
            base[bucket].append(base_ret)

            # COA 1: limit entry on bar i+1, then manage from i+2
            lim = doc.entry_limit(closes[i], bias, a)
            fb = bars[i + 1]  # (date,o,h,l,c)
            filled = (fb[3] <= lim) if sign > 0 else (fb[2] >= lim)
            if not filled:
                continue
            fills += 1
            plan = doc.exit_plan(lim, bias, a)
            r = sim_doctrine(bars, i + 2, sign, lim, plan, doc)
            if r is not None:
                coa1[bucket].append(r)

    print("=" * 72)
    print("COA 1 DOCTRINE vs PLAIN 5-DAY HOLD  (same momentum signals, net 10bps)")
    print("=" * 72)
    print(f"signals: {signals} | limit fills: {fills} ({100*fills/max(1,signals):.0f}% fill rate)")
    print()
    for split in ("train", "test"):
        b, c = stats(base[split]), stats(coa1[split])
        tag = "TRAIN (<2015)" if split == "train" else "TEST  (>=2015)"
        print(f"--- {tag} ---")
        print(f"  baseline hold : {b}")
        print(f"  COA 1 doctrine: {c}")
        if b and c:
            dm = round(c["mean"] - b["mean"], 3)
            print(f"  verdict: doctrine mean {'+' if dm>=0 else ''}{dm}%/trade vs baseline"
                  f"  ({'ADDS' if c['sharpe_per_trade']>b['sharpe_per_trade'] else 'HURTS'} "
                  f"risk-adjusted)")
        print()
    print("Read: COA 1 justified only if it beats baseline on BOTH mean and per-trade")
    print("Sharpe, out-of-sample. Otherwise the ladder/stop is destroying the edge.")


if __name__ == "__main__":
    main()
