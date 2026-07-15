"""
Signal research harness — test documented factor hypotheses against the gauntlet.

The rebuild rule, learned the hard way: no hand-tuned heuristic gets near the
execution engine until it beats a coin flip out-of-sample on 28 years of data.
This tests DIRECTIONAL rules (each maps price history -> BULLISH/BEARISH) with the
same discipline as the core backtest: fixed forward horizon, non-overlapping
independent windows, drift-robust metrics (balanced accuracy + MCC), and a
train/test time split so nothing is fit to the same data it's judged on.

Hypotheses (all documented anomalies, defined precisely — not invented knobs):
  old_mom20   : buy what rose over 20d (the OLD signal's continuation bet) — control
  st_rev_5    : FADE the 5-day move  (short-term reversal)
  st_rev_20   : FADE the 20-day move
  st_rev_1    : FADE yesterday       (very short reversal)
  mom_12_1    : 12-month momentum skipping last month (Jegadeesh-Titman)
  mom_6_1     : 6-month momentum skipping last month
  trend_200   : price above/below 200-day average (time-series trend)
"""
import csv
import glob
import math
import os

DECISIVE = 1.0
SPLIT_DATE = "2015-01-01"   # train < split <= test
MIN_LOOKBACK = 252


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


def factors(closes, i):
    """Each returns 'BULLISH'/'BEARISH' from PAST-ONLY data at index i, or None."""
    c = closes
    def r(days):
        base = c[i - days]
        return (c[i] / base - 1) if base > 0 else None
    out = {}
    r1, r5, r20 = r(1), r(5), r(20)
    out["old_mom20"] = ("BULLISH" if r20 > 0 else "BEARISH") if r20 is not None else None
    out["st_rev_5"] = ("BEARISH" if r5 > 0 else "BULLISH") if r5 is not None else None
    out["st_rev_20"] = ("BEARISH" if r20 > 0 else "BULLISH") if r20 is not None else None
    out["st_rev_1"] = ("BEARISH" if r1 > 0 else "BULLISH") if r1 is not None else None
    m12 = (c[i - 21] / c[i - 252] - 1) if c[i - 252] > 0 else None
    m6 = (c[i - 21] / c[i - 126] - 1) if c[i - 126] > 0 else None
    out["mom_12_1"] = ("BULLISH" if m12 > 0 else "BEARISH") if m12 is not None else None
    out["mom_6_1"] = ("BULLISH" if m6 > 0 else "BEARISH") if m6 is not None else None
    ma200 = sum(c[i - 200:i]) / 200
    out["trend_200"] = "BULLISH" if c[i] > ma200 else "BEARISH"
    return out


def mcc(tp, tn, fp, fn):
    den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return round((tp * tn - fp * fn) / den, 4) if den else 0.0


def score(samples):
    # balanced accuracy over decisive calls + MCC + significance z
    dec = [s for s in samples if s["decisive"]]
    if not dec:
        return None
    bull = [s for s in dec if s["bias"] == "BULLISH"]
    bear = [s for s in dec if s["bias"] == "BEARISH"]
    bh = sum(1 for s in bull if s["correct"]) / len(bull) if bull else None
    rh = sum(1 for s in bear if s["correct"]) / len(bear) if bear else None
    avail = [x for x in (bh, rh) if x is not None]
    bal = sum(avail) / len(avail) if avail else None
    tp = sum(1 for s in dec if s["bias"] == "BULLISH" and s["real_up"])
    fp = sum(1 for s in dec if s["bias"] == "BULLISH" and not s["real_up"])
    tn = sum(1 for s in dec if s["bias"] == "BEARISH" and not s["real_up"])
    fn = sum(1 for s in dec if s["bias"] == "BEARISH" and s["real_up"])
    n = len(dec)
    hit = sum(1 for s in dec if s["correct"]) / n
    z = (hit - 0.5) / (0.5 / math.sqrt(n)) if n else 0
    return {"n": n, "bal_acc": round(bal, 4) if bal else None,
            "mcc": mcc(tp, tn, fp, fn), "z": round(z, 1),
            "mean_dir_ret": round(sum(s["dir_ret"] for s in dec) / n, 3)}


def run(horizon):
    csvs = sorted(glob.glob("app/data/historical/*_daily.csv"))
    names = ["old_mom20", "st_rev_1", "st_rev_5", "st_rev_20",
             "mom_6_1", "mom_12_1", "trend_200"]
    train = {k: [] for k in names}
    test = {k: [] for k in names}

    for p in csvs:
        closes_dated = load(p)
        dates = [d for d, _ in closes_dated]
        c = [x for _, x in closes_dated]
        n = len(c)
        for i in range(MIN_LOOKBACK, n - horizon, horizon):
            if c[i] <= 0:
                continue
            raw = (c[i + horizon] / c[i] - 1) * 100
            fac = factors(c, i)
            bucket = test if dates[i] >= SPLIT_DATE else train
            for k in names:
                bias = fac[k]
                if bias is None:
                    continue
                dir_ret = raw if bias == "BULLISH" else -raw
                bucket[k].append({
                    "bias": bias, "real_up": raw > 0,
                    "correct": dir_ret > 0, "dir_ret": dir_ret,
                    "decisive": abs(raw) >= DECISIVE,
                })

    print(f"\n{'='*78}\nFACTOR PANEL  |  forward horizon = {horizon} trading days\n{'='*78}")
    print(f"{'factor':>12} | {'TRAIN (<2015)':^34} | {'TEST (>=2015)':^34}")
    print(f"{'':>12} | {'bal_acc':>8} {'mcc':>7} {'z':>6} {'n':>9} | {'bal_acc':>8} {'mcc':>7} {'z':>6} {'n':>9}")
    print("-" * 78)
    for k in names:
        tr, te = score(train[k]), score(test[k])
        def fmt(s):
            return (f"{s['bal_acc']:>8} {s['mcc']:>7} {s['z']:>6} {s['n']:>9}"
                    if s else f"{'--':>8} {'--':>7} {'--':>6} {'--':>9}")
        print(f"{k:>12} | {fmt(tr)} | {fmt(te)}")
    print("\nEDGE = bal_acc > 0.50 AND mcc > 0 AND |z| large, CONSISTENT across train & test.")
    print("A factor that only works in TRAIN is overfit. Sign matters: reversal vs momentum.")


if __name__ == "__main__":
    for h in (5, 20):
        run(h)
