"""
War-game the RUNNER hybrid: bank TP1/2/3, let the 4th tranche run on a trailing stop.

Tests, paired on the same momentum signals, net 10bps, out-of-sample:
  baseline    : plain 5-day hold
  H1          : Thomas's idea -- 1.5-ATR stop, TP1/2/3 at 1.5/3/4.5 ATR (25% each),
                last 25% runs on a 3-ATR trailing stop after TP3
  H2          : H1 but a WIDER 2.5-ATR initial stop (the tight stop was a culprit)
  trail-only  : known-good reference -- no fixed TPs, 3-ATR trail on the whole position
"""
import glob
import math

import doctrine_backtest as D
from app.services.directional_signal_engine import DirectionalSignalEngine

TP_ATRS = (1.5, 3.0, 4.5)     # three fixed targets, in ATR
SCALE = (0.25, 0.25, 0.25)    # bank 25% at each; leftover 25% is the runner
TRAIL_ATR = 3.0
COST = D.COST_RT_PCT / 100    # fraction


def sim(bars, start, sign, entry, atr, stop_atr):
    stop = entry - sign * stop_atr * atr
    tps = [entry + sign * t * atr for t in TP_ATRS]
    remaining, hit, realized, ext = 1.0, 0, 0.0, entry
    end = min(start + D.MAX_HOLD, len(bars))
    for j in range(start, end):
        _, o, h, l, c = bars[j]
        # stop first (conservative), gap-aware
        if sign > 0:
            if l <= stop:
                fill = o if o <= stop else stop
                return realized + remaining * (fill / entry - 1) * sign - COST
            ext = max(ext, h)
        else:
            if h >= stop:
                fill = o if o >= stop else stop
                return realized + remaining * (entry / fill - 1) - COST
            ext = min(ext, l)
        # fixed TPs
        while hit < 3:
            tp = tps[hit]
            reached = (h >= tp) if sign > 0 else (l <= tp)
            if not reached:
                break
            fill = (o if o >= tp else tp) if sign > 0 else (o if o <= tp else tp)
            frac = min(SCALE[hit], remaining)
            realized += frac * ((fill / entry - 1) * sign if sign > 0 else (entry / fill - 1))
            remaining -= frac
            hit += 1
            # ratchet stop up the ladder for the still-open portion
            stop = entry if hit == 1 else tps[hit - 2]
        if remaining <= 1e-9:
            return realized - COST
        # once the ladder is done, the runner trails
        if hit >= 3:
            trail = ext - sign * TRAIL_ATR * atr
            stop = max(stop, trail) if sign > 0 else min(stop, trail)
    # max hold: exit remainder at close
    c = bars[end - 1][4]
    realized += remaining * ((c / entry - 1) * sign if sign > 0 else (entry / c - 1))
    return realized - COST


def sim_trailonly(bars, start, sign, entry, atr):
    stop = entry - sign * TRAIL_ATR * atr
    ext = entry
    end = min(start + D.MAX_HOLD, len(bars))
    for j in range(start, end):
        _, o, h, l, c = bars[j]
        if sign > 0:
            if l <= stop:
                return (min(o, stop) / entry - 1) - COST
            ext = max(ext, h); stop = max(stop, ext - TRAIL_ATR * atr)
        else:
            if h >= stop:
                return (entry / max(o, stop) - 1) - COST
            ext = min(ext, l); stop = min(stop, ext + TRAIL_ATR * atr)
    c = bars[end - 1][4]
    return ((c / entry - 1) * sign) - COST


def st(xs):
    n = len(xs)
    if n < 10:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) or 1e-9
    return (round(m * 100, 3), round(m / sd, 3), round(100 * sum(1 for x in xs if x > 0) / n, 1), n)


def main():
    sig = DirectionalSignalEngine()
    R = {k: {"tr": [], "te": []} for k in ("base", "h1", "h2", "trail")}
    for p in sorted(glob.glob("app/data/historical/*_daily.csv")):
        bars = D.load(p); closes = [b[4] for b in bars]; atr = D.atr_series(bars); n = len(bars)
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
            R["h1"][b].append(sim(bars, i + 1, sign, e, a, 1.5))
            R["h2"][b].append(sim(bars, i + 1, sign, e, a, 2.5))
            R["trail"][b].append(sim_trailonly(bars, i + 1, sign, e, a))
    print("RUNNER HYBRID war-game  (mean%/trade, per-trade Sharpe, win%, n) net 10bps")
    for split, lbl in (("te", "TEST (>=2015)"), ("tr", "TRAIN (<2015)")):
        print(f"\n--- {lbl} ---")
        for k, name in (("base", "baseline hold "), ("h1", "H1 runner 1.5stop"),
                        ("h2", "H2 runner 2.5stop"), ("trail", "trail-only ref ")):
            print(f"  {name}: {st(R[k][split])}")


if __name__ == "__main__":
    main()
