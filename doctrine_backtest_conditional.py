"""
CONDITIONAL RUNNER war-game: run the tail only "when the analysis supports it".

At the moment TP3 fills, judge whether the trend is intact (close vs 50-day SMA, in the
trade's direction):
  * intact  -> let the final 25% RUN on the 3-ATR trailing stop (H2 behaviour)
  * broken  -> BANK the runner now at TP3 (take the profit; don't give it back)

Compared paired against unconditional H2 and the plain-hold baseline, net 10bps, OOS.
If conditioning doesn't beat H2, the simpler unconditional runner stands.
"""
import glob
import math

import doctrine_backtest as D
from app.services.directional_signal_engine import DirectionalSignalEngine
from app.services.trade_doctrine_engine import TradeDoctrineEngine

COST = D.COST_RT_PCT / 100
SMA_N = 50
TRAIL = TradeDoctrineEngine.RUNNER_TRAIL_ATR
STOP_ATR = TradeDoctrineEngine.STOP_ATR_MULT
TP_ATRS = TradeDoctrineEngine.TARGET_ATRS


def sma(closes, n):
    out = [0.0] * len(closes)
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= n:
            s -= closes[i - n]
        out[i] = s / min(i + 1, n)
    return out


def sim(bars, start, sign, entry, atr, closes, sma50, conditional):
    stop = entry - sign * STOP_ATR * atr
    tps = [entry + sign * t * atr for t in TP_ATRS]
    remaining, hit, realized, ext = 1.0, 0, 0.0, entry
    end = min(start + D.MAX_HOLD, len(bars))
    for j in range(start, end):
        _, o, h, l, c = bars[j]
        if sign > 0:
            if l <= stop:
                return realized + remaining * ((o if o <= stop else stop) / entry - 1) - COST
            ext = max(ext, h)
        else:
            if h >= stop:
                return realized + remaining * (entry / (o if o >= stop else stop) - 1) - COST
            ext = min(ext, l)
        while hit < 3:
            tp = tps[hit]
            reached = (h >= tp) if sign > 0 else (l <= tp)
            if not reached:
                break
            fill = (o if o >= tp else tp) if sign > 0 else (o if o <= tp else tp)
            frac = min(0.25, remaining)
            realized += frac * ((fill / entry - 1) if sign > 0 else (entry / fill - 1))
            remaining -= frac
            hit += 1
            stop = entry if hit == 1 else tps[hit - 2]
            if hit == 3 and conditional:
                # analysis check: is the trend intact at TP3?
                intact = (c > sma50[j]) if sign > 0 else (c < sma50[j])
                if not intact and remaining > 1e-9:
                    realized += remaining * ((fill / entry - 1) if sign > 0 else (entry / fill - 1))
                    return realized - COST
        if remaining <= 1e-9:
            return realized - COST
        if hit >= 3:
            trail = ext - sign * TRAIL * atr
            stop = max(stop, trail) if sign > 0 else min(stop, trail)
    c = bars[end - 1][4]
    realized += remaining * ((c / entry - 1) if sign > 0 else (entry / c - 1))
    return realized - COST


def st(xs):
    n = len(xs)
    if n < 10:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) or 1e-9
    return (round(m * 100, 3), round(m / sd, 3), round(100 * sum(1 for x in xs if x > 0) / n, 1), n)


def main():
    sig = DirectionalSignalEngine()
    R = {k: {"tr": [], "te": []} for k in ("base", "h2", "cond")}
    for p in sorted(glob.glob("app/data/historical/*_daily.csv")):
        bars = D.load(p); closes = [b[4] for b in bars]; atr = D.atr_series(bars)
        sma50 = sma(closes, SMA_N); n = len(bars)
        for i in range(D.MIN_HISTORY, n - D.MAX_HOLD - 2, D.STEP):
            s = sig.evaluate(closes[:i + 1])
            if not s.get("tradeable"):
                continue
            sign = 1 if s["directional_bias"] == "BULLISH" else -1
            a = atr[i]
            if a <= 0 or closes[i] <= 0:
                continue
            b = "te" if bars[i][0] >= "2015-01-01" else "tr"
            e = closes[i]
            R["base"][b].append((closes[i + D.STEP] / closes[i] - 1) * sign - COST)
            R["h2"][b].append(sim(bars, i + 1, sign, e, a, closes, sma50, conditional=False))
            R["cond"][b].append(sim(bars, i + 1, sign, e, a, closes, sma50, conditional=True))
    print("CONDITIONAL RUNNER war-game (mean%/trade, Sharpe, win%, n) net 10bps")
    for split, lbl in (("te", "TEST (>=2015)"), ("tr", "TRAIN (<2015)")):
        print(f"\n--- {lbl} ---")
        for k, name in (("base", "baseline hold  "), ("h2", "H2 always-run  "),
                        ("cond", "conditional-run")):
            print(f"  {name}: {st(R[k][split])}")


if __name__ == "__main__":
    main()
