"""
Faithful CORE backtest — does GreyLine's price-derived directional signal predict?

Scope, stated honestly:
  * Reuses GreyLine's OWN historical scorer (HistoricalOpportunityScoringEngine),
    so this measures the real price-derived signal, not a reimplementation.
  * It does NOT and cannot validate the live institutional-flow overlay — that data
    doesn't exist historically; the historical scorer proxies it from price. So this
    is the most CHARITABLE test of the core: if it fails here, the live edge would
    have to come entirely from the flow overlay.
  * Grading is drift-safe: fixed forward horizon, strictly future prices, and
    NON-OVERLAPPING windows so samples are independent. Verdict is balanced accuracy
    and Matthews correlation (both 0 for any drift/constant predictor) with n, not a
    single cherry-pickable equity number.

Mechanics verified clean in audit: score at day T's close using past-only history,
outcome from T -> T+H close (future). No lookahead.
"""
import csv
import glob
import math
import os
from collections import defaultdict

from app.services.simulation.historical_opportunity_scoring_engine import (
    HistoricalOpportunityScoringEngine,
)

HORIZON_DAYS = 5      # forward holding window (trading days)
DECISIVE_PCT = 1.0    # |move| below this is a non-call, excluded from accuracy
MIN_HISTORY = 30      # bars the builder needs behind a decision
EXEC_COMPOSITE = 85   # live EXECUTE threshold
EXEC_DIRCONF = 5      # live direction-confidence threshold


def load_closes(path):
    out = []
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                out.append((row["date"][:10], float(row["close"])))
            except (ValueError, KeyError, TypeError):
                pass
    out.sort()
    return out


def mcc(tp, tn, fp, fn):
    num = tp * tn - fp * fn
    den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return round(num / den, 4) if den else 0.0


def balanced_accuracy(samples):
    # mean of per-direction hit rates; > 0.5 = real directional skill, drift-immune
    out = {}
    for d in ("BULLISH", "BEARISH"):
        sub = [s for s in samples if s["bias"] == d]
        hits = sum(1 for s in sub if s["correct"])
        out[d] = (hits / len(sub)) if sub else None
        out[d + "_n"] = len(sub)
    avail = [v for k, v in out.items() if not k.endswith("_n") and v is not None]
    out["balanced"] = round(sum(avail) / len(avail), 4) if avail else None
    return out


def skill(samples):
    if not samples:
        return {"n": 0}
    tp = sum(1 for s in samples if s["bias"] == "BULLISH" and s["real_up"])
    fp = sum(1 for s in samples if s["bias"] == "BULLISH" and not s["real_up"])
    tn = sum(1 for s in samples if s["bias"] == "BEARISH" and not s["real_up"])
    fn = sum(1 for s in samples if s["bias"] == "BEARISH" and s["real_up"])
    ba = balanced_accuracy(samples)
    return {
        "n": len(samples),
        "balanced_accuracy": ba["balanced"],
        "bullish_hit": round(ba["BULLISH"], 4) if ba["BULLISH"] is not None else None,
        "bearish_hit": round(ba["BEARISH"], 4) if ba["BEARISH"] is not None else None,
        "bullish_n": ba["BULLISH_n"],
        "bearish_n": ba["BEARISH_n"],
        "mcc": mcc(tp, tn, fp, fn),
        "mean_directional_return_pct": round(sum(s["dir_ret"] for s in samples) / len(samples), 3),
    }


def main():
    eng = HistoricalOpportunityScoringEngine()
    csvs = sorted(glob.glob("app/data/historical/*_daily.csv"))

    all_samples = []           # every decisive call
    all_returns_up = 0         # base rate numerator (any move up)
    all_returns_n = 0
    processed = 0

    for path in csvs:
        sym = os.path.basename(path).replace("_daily.csv", "")
        closes = load_closes(path)
        n = len(closes)
        # non-overlapping forward windows -> independent samples
        for i in range(MIN_HISTORY, n - HORIZON_DAYS, HORIZON_DAYS):
            date_i, close_i = closes[i]
            fwd = closes[i + HORIZON_DAYS][1]
            if close_i <= 0:
                continue
            raw = (fwd / close_i - 1) * 100
            all_returns_up += 1 if raw > 0 else 0
            all_returns_n += 1

            res = eng.score_snapshot(sym, date_i)
            opp = res.get("opportunity") or {}
            if not opp.get("candidate_available"):
                continue
            bias = opp.get("directional_bias")
            if bias not in ("BULLISH", "BEARISH"):
                continue

            dir_ret = raw if bias == "BULLISH" else -raw
            if abs(raw) < DECISIVE_PCT:
                continue  # non-decisive move, excluded from accuracy

            all_samples.append({
                "sym": sym,
                "composite": float(opp.get("composite_score") or 0),
                "dirconf": float(opp.get("direction_confidence") or 0),
                "result": opp.get("result"),
                "bias": bias,
                "raw": raw,
                "real_up": raw > 0,
                "dir_ret": dir_ret,
                "correct": dir_ret > 0,
            })
        processed += 1

    base_rate = round(100 * all_returns_up / all_returns_n, 2) if all_returns_n else 0

    print("=" * 68)
    print("GREYLINE CORE BACKTEST  (price-derived signal, flow overlay excluded)")
    print("=" * 68)
    print(f"symbols processed      : {processed}")
    print(f"forward horizon        : {HORIZON_DAYS} trading days, non-overlapping")
    print(f"decisive |move| cutoff : {DECISIVE_PCT}%")
    print(f"market base rate (up)  : {base_rate}%   <- a coin that always says UP scores this")
    print(f"decisive calls (n)     : {len(all_samples)}")
    print()

    overall = skill(all_samples)
    print("--- ALL directional calls ---")
    for k, v in overall.items():
        print(f"  {k:28}: {v}")
    print()

    execs = [s for s in all_samples if s["composite"] >= EXEC_COMPOSITE and s["dirconf"] >= EXEC_DIRCONF]
    print(f"--- EXECUTE-grade only (composite>={EXEC_COMPOSITE} AND dirconf>={EXEC_DIRCONF}) — what it would TRADE ---")
    ex = skill(execs)
    for k, v in ex.items():
        print(f"  {k:28}: {v}")
    print()

    print("--- accuracy by composite-score band (does a higher score predict better?) ---")
    bands = [(0, 55), (55, 65), (65, 75), (75, 85), (85, 200)]
    print(f"  {'band':>12} {'n':>7} {'bal_acc':>9} {'mcc':>8} {'mean_ret%':>10}")
    for lo, hi in bands:
        sub = [s for s in all_samples if lo <= s["composite"] < hi]
        sk = skill(sub)
        ba = sk.get("balanced_accuracy")
        print(f"  {str(lo)+'-'+str(hi):>12} {sk['n']:>7} "
              f"{(ba if ba is not None else float('nan')):>9} {sk.get('mcc'):>8} "
              f"{sk.get('mean_directional_return_pct'):>10}")
    print()
    print("VERDICT KEY: balanced_accuracy > 0.50 and mcc > 0 (with large n) = real edge.")
    print("If bands do NOT trend up with score, the score carries no information.")


if __name__ == "__main__":
    main()
