import glob
import json
import math
import os
from datetime import datetime
from pathlib import Path

from app.services.price_history_store import PriceHistoryStore


class UWFlowGradingEngine:
    """
    Does Unusual Whales flow predict forward returns? Measured, not assumed.

    For each symbol and day, aggregate the day's flow to a directional reading, then grade
    it against the NEXT day's underlying return. Two candidate features are graded in
    parallel — nobody knows which predicts, so the data decides:
      * directional_flow : ask-side call-vs-put premium imbalance (aggressive buying)
      * net_premium      : total signed premium (all flow, incl. sells)

    Same discipline that rescued the price signal, so this can't fool us the way the old
    system fooled itself:
      * DAILY aggregation with distinct-days independence — flow and returns within one day
        are one observation, not many (the correlated-sample trap).
      * Drift-robust verdict: balanced accuracy + Matthews correlation, not raw hit rate.
      * Refuses a verdict below MIN_DISTINCT_DAYS no matter how the P&L looks.

    Measurement ONLY. This does not touch the live decision. Flow earns a place in the
    signal only after it proves an edge here — and today the data is days deep, so the
    honest verdict is INSUFFICIENT.
    """

    FLOW_DIR = Path("app/data/uw_flow")
    HORIZON_DAYS = 1
    MIN_DISTINCT_DAYS = 20
    DECISIVE_PCT = 0.5   # |move| below this (%) is intraday noise, excluded from accuracy

    def __init__(self):
        self.price = PriceHistoryStore()

    def _symbols(self):
        return sorted(os.path.basename(p)[:-6] for p in glob.glob(str(self.FLOW_DIR / "*.jsonl")))

    def _daily_flow(self, symbol):
        """{date: {directional_flow: mean, net_premium: sum}} from the compact series."""
        path = self.FLOW_DIR / f"{symbol}.jsonl"
        if not path.exists():
            return {}
        agg = {}
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            day = str(r.get("ts") or "")[:10]
            if not day:
                continue
            a = agg.setdefault(day, {"df": [], "np": 0.0})
            a["df"].append(float(r.get("directional_flow") or 0))
            a["np"] += float(r.get("net_premium") or 0)
        return {d: {"directional_flow": sum(a["df"]) / len(a["df"]) if a["df"] else 0,
                    "net_premium": a["np"]}
                for d, a in agg.items()}

    def _daily_close(self, symbol):
        """{date: last recorded price that day} from the forward price feed."""
        by_day = {}
        for dt, px in self.price._load(symbol):   # sorted ascending -> last write wins
            by_day[dt.date().isoformat()] = px
        return by_day

    @staticmethod
    def _mcc(tp, tn, fp, fn):
        den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        return round((tp * tn - fp * fn) / den, 4) if den else 0.0

    def _verdict(self, samples):
        dec = [s for s in samples if s["decisive"]]
        n = len(dec)
        days = len({s["day"] for s in dec})
        if not n:
            return {"n": 0, "distinct_days": days, "verdict": "NO_DATA"}
        bull = [s for s in dec if s["bias"] == "BULLISH"]
        bear = [s for s in dec if s["bias"] == "BEARISH"]
        bh = sum(1 for s in bull if s["correct"]) / len(bull) if bull else None
        rh = sum(1 for s in bear if s["correct"]) / len(bear) if bear else None
        avail = [x for x in (bh, rh) if x is not None]
        bal = round(sum(avail) / len(avail), 4) if avail else None
        tp = sum(1 for s in dec if s["bias"] == "BULLISH" and s["real_up"])
        fp = sum(1 for s in dec if s["bias"] == "BULLISH" and not s["real_up"])
        tn = sum(1 for s in dec if s["bias"] == "BEARISH" and not s["real_up"])
        fn = sum(1 for s in dec if s["bias"] == "BEARISH" and s["real_up"])
        mcc = self._mcc(tp, tn, fp, fn)

        if days < self.MIN_DISTINCT_DAYS:
            verdict = "INSUFFICIENT_SAMPLE"
        elif bal is not None and bal > 0.5 and mcc > 0:
            verdict = "PREDICTIVE"
        elif bal is not None and bal < 0.5 and mcc < 0:
            verdict = "ANTI_PREDICTIVE"
        else:
            verdict = "NO_DETECTABLE_EDGE"
        return {"n": n, "distinct_days": days, "balanced_accuracy": bal,
                "mcc": mcc, "verdict": verdict}

    def grade(self):
        features = ("directional_flow", "net_premium")
        samples = {f: [] for f in features}

        for symbol in self._symbols():
            flow = self._daily_flow(symbol)
            closes = self._daily_close(symbol)
            days = sorted(set(flow) & set(closes))
            for i, d in enumerate(days):
                # next available trading day at least HORIZON_DAYS ahead
                fwd = next((fd for fd in days[i + 1:] if fd > d), None)
                if not fwd or closes[d] <= 0:
                    continue
                raw = (closes[fwd] / closes[d] - 1) * 100
                decisive = abs(raw) >= self.DECISIVE_PCT
                for f in features:
                    val = flow[d][f]
                    bias = "BULLISH" if val > 0 else "BEARISH"
                    dir_ret = raw if bias == "BULLISH" else -raw
                    samples[f].append({"symbol": symbol, "day": d, "bias": bias,
                                       "real_up": raw > 0, "correct": dir_ret > 0,
                                       "decisive": decisive})

        per_feature = {f: self._verdict(samples[f]) for f in features}
        overall = "INSUFFICIENT_SAMPLE"
        if all(v.get("verdict") not in ("INSUFFICIENT_SAMPLE", "NO_DATA")
               for v in per_feature.values()):
            overall = "MEASURED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "UWFlowGradingEngine",
            "horizon_days": self.HORIZON_DAYS,
            "min_distinct_days": self.MIN_DISTINCT_DAYS,
            "symbols_graded": len(self._symbols()),
            "overall": overall,
            "features": per_feature,
            "note": ("Measurement only — flow does not affect live decisions. Needs "
                     f"{self.MIN_DISTINCT_DAYS}+ distinct days per feature before a verdict; "
                     "below that it is INSUFFICIENT no matter how it looks."),
            "status": "UW_FLOW_GRADING_READY",
        }
