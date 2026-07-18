"""
Stage 3 validation: does a LIMIT entry (pullback to a better price) beat a MARKET entry?

Paired on the same momentum signals, same validated H2 exit doctrine, net 10bps, OOS.
  * market : enter at the signal close, manage from the next bar.
  * limit@X: place a limit X ATR better; fills only if the next bar trades through it,
             else NO TRADE. Manage from the bar after the fill.

The suspected catch is ADVERSE SELECTION: the trades a limit misses may be the ones that
gapped/ran away — the winners. So beyond per-trade return, we measure the MARKET return of
the signals the limit MISSED vs. the ones it FILLED. If missed >> filled, the limit is
systematically skipping the best trades, and "a better price" is an illusion.
"""
import glob
import math

import doctrine_backtest as D
from app.services.directional_signal_engine import DirectionalSignalEngine
from app.services.trade_doctrine_engine import TradeDoctrineEngine

COST = D.COST_RT_PCT / 100
STOP_ATR = TradeDoctrineEngine.STOP_ATR_MULT
TP_ATRS = TradeDoctrineEngine.TARGET_ATRS
TRAIL = TradeDoctrineEngine.RUNNER_TRAIL_ATR
PULLBACKS = (0.1, 0.25, 0.5)   # ATR


def h2(bars, start, sign, entry, atr):
    """The validated H2 exit lifecycle. Return net fraction, or None."""
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
            if not ((h >= tp) if sign > 0 else (l <= tp)):
                break
            fill = (o if o >= tp else tp) if sign > 0 else (o if o <= tp else tp)
            frac = min(0.25, remaining)
            realized += frac * ((fill / entry - 1) if sign > 0 else (entry / fill - 1))
            remaining -= frac
            hit += 1
            stop = entry if hit == 1 else tps[hit - 2]
        if remaining <= 1e-9:
            return realized - COST
        if hit >= 3:
            trail = ext - sign * TRAIL * atr
            stop = max(stop, trail) if sign > 0 else min(stop, trail)
    c = bars[end - 1][4]
    return realized + remaining * ((c / entry - 1) if sign > 0 else (entry / c - 1)) - COST


def st(xs):
    n = len(xs)
    if n < 10:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) or 1e-9
    return {"mean%": round(m * 100, 3), "sharpe": round(m / sd, 3),
            "win%": round(100 * sum(1 for x in xs if x > 0) / n, 1), "n": n}


def main():
    sig = DirectionalSignalEngine()
    mkt = {"tr": [], "te": []}
    lim = {pb: {"tr": [], "te": []} for pb in PULLBACKS}
    # adverse-selection: market return of signals each limit FILLED vs MISSED (test only)
    adv = {pb: {"filled": [], "missed": []} for pb in PULLBACKS}

    for p in sorted(glob.glob("app/data/historical/*_daily.csv")):
        bars = D.load(p); closes = [b[4] for b in bars]; atr = D.atr_series(bars); n = len(bars)
        for i in range(D.MIN_HISTORY, n - D.MAX_HOLD - 3, D.STEP):
            s = sig.evaluate(closes[:i + 1])
            if not s.get("tradeable"):
                continue
            sign = 1 if s["directional_bias"] == "BULLISH" else -1
            a = atr[i]
            if a <= 0 or closes[i] <= 0:
                continue
            bk = "te" if bars[i][0] >= "2015-01-01" else "tr"
            mret = h2(bars, i + 1, sign, closes[i], a)      # market entry
            mkt[bk].append(mret)
            nb = bars[i + 1]                                 # fill bar
            for pb in PULLBACKS:
                limit = closes[i] - sign * pb * a
                filled = (nb[3] <= limit) if sign > 0 else (nb[2] >= limit)
                if filled:
                    lim[pb][bk].append(h2(bars, i + 2, sign, limit, a))
                    if bk == "te":
                        adv[pb]["filled"].append(mret)
                elif bk == "te":
                    adv[pb]["missed"].append(mret)

    print("STAGE 3: LIMIT vs MARKET entry (H2 exit, net 10bps)")
    for split, lbl in (("te", "TEST (>=2015)"), ("tr", "TRAIN (<2015)")):
        print(f"\n--- {lbl} ---")
        print(f"  market entry     : {st(mkt[split])}")
        for pb in PULLBACKS:
            filled = len(lim[pb][split])
            fr = round(100 * filled / max(1, len(mkt[split])), 0)
            print(f"  limit @{pb} ATR   : {st(lim[pb][split])}  fill={fr:.0f}%")
    print("\n--- ADVERSE SELECTION (TEST): market return of signals the limit filled vs missed ---")
    for pb in PULLBACKS:
        f = st(adv[pb]["filled"]); m = st(adv[pb]["missed"])
        fm = f["mean%"] if f else None
        mm = m["mean%"] if m else None
        flag = "MISSES WINNERS" if (fm is not None and mm is not None and mm > fm) else "filters ok"
        print(f"  limit @{pb} ATR: filled-signal mkt {fm}%  vs  missed-signal mkt {mm}%  -> {flag}")


if __name__ == "__main__":
    main()
