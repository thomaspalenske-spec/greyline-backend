from datetime import datetime, timedelta
from os import getenv
from pathlib import Path

from app.services.persistence.json_store import read_jsonl
from app.services.price_history_store import PriceHistoryStore, _parse
from app.services.skill_metrics_engine import SkillMetricsEngine

FAVORABLE = "FAVORABLE"
UNFAVORABLE = "UNFAVORABLE"
NEUTRAL = "NEUTRAL"
PENDING = "PENDING_NO_FORWARD_PRICE"


class FixedHorizonGraderEngine:
    """
    Drift-free outcome grading: grade each decision at snapshot_time + a FIXED horizon,
    using the price nearest that target time — NOT the current price (the confound that
    made GreyLine's edge unmeasurable).

    Forward price source is a symbol->sorted[(ts, price)] index built from every recorded
    snapshot (decision logs + PriceHistoryStore). A decision's forward price is simply a
    later snapshot for the same symbol near T + horizon. Decisions younger than the horizon
    (no matured forward price) grade PENDING — honestly, not against "now".
    """

    def __init__(self, horizon_hours=None, tolerance_hours=None):
        self.horizon_hours = float(getenv("GREYLINE_GRADING_HORIZON_HOURS", "24")) if horizon_hours is None else float(horizon_hours)
        self.tolerance_hours = (self.horizon_hours / 4) if tolerance_hours is None else float(tolerance_hours)
        self.ledger = Path("app/data/opportunity_memory/opportunity_outcome_ledger.jsonl")
        self.store = PriceHistoryStore()

    def _build_index(self, decisions):
        index = {}
        # decision snapshots
        for d in decisions:
            self._add_point(index, d.get("symbol"), d.get("snapshot_price"), d.get("timestamp"))
        # persisted live price history (forward-accumulated, cleaner going forward)
        for d in decisions:
            sym = str(d.get("symbol") or "").upper()
            if sym and sym not in index.get("_loaded_store", set()):
                index.setdefault("_loaded_store", set()).add(sym)
        for sym in list(index.get("_loaded_store", set())):
            for dt, price in self.store._load(sym):
                index.setdefault(sym, []).append((dt, price))
        for sym, pts in index.items():
            if sym != "_loaded_store":
                pts.sort(key=lambda x: x[0])
        index.pop("_loaded_store", None)
        return index

    @staticmethod
    def _add_point(index, symbol, price, ts):
        if not symbol or price in (None, 0):
            return
        dt = _parse(ts)
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        if dt is None or price <= 0:
            return
        index.setdefault(str(symbol).upper(), []).append((dt, price))

    def _price_at(self, index, symbol, target_dt):
        pts = index.get(str(symbol).upper())
        if not pts:
            return None
        best = min(pts, key=lambda p: abs((p[0] - target_dt).total_seconds()))
        age = abs((best[0] - target_dt).total_seconds())
        if age > self.tolerance_hours * 3600:
            return None
        return {"price": best[1], "age_seconds": round(age, 1)}

    def grade(self, decisions=None):
        decisions = decisions if decisions is not None else read_jsonl(self.ledger)
        index = self._build_index(decisions)
        horizon = timedelta(hours=self.horizon_hours)

        counts = {FAVORABLE: 0, UNFAVORABLE: 0, NEUTRAL: 0, PENDING: 0}
        graded = []
        for d in decisions:
            symbol = d.get("symbol")
            snap = d.get("snapshot_price")
            ts = _parse(d.get("timestamp"))
            bias = str(d.get("directional_bias") or "").upper()
            result = d.get("result")

            try:
                snap = float(snap)
            except (TypeError, ValueError):
                snap = 0
            if ts is None or snap <= 0 or bias not in ("BULLISH", "BEARISH"):
                counts[PENDING] += 1
                continue

            fwd = self._price_at(index, symbol, ts + horizon)
            if not fwd:
                counts[PENDING] += 1
                continue

            raw = (fwd["price"] / snap - 1) * 100
            directional = raw if bias == "BULLISH" else -raw
            if directional >= 1.0:
                grade = FAVORABLE
            elif directional <= -1.0:
                grade = UNFAVORABLE
            else:
                grade = NEUTRAL
            counts[grade] += 1
            graded.append({
                "symbol": symbol, "directional_bias": bias, "result": result,
                "directional_return_pct": round(directional, 4),
                "forward_price_age_s": fwd["age_seconds"],
                "grade": grade,
            })

        # Drift-robust skill metric: raw hit rate is dominated by the market's move over
        # the window (bullish/bearish land on opposite extremes when the market trends).
        # Balanced accuracy = mean of per-direction hit rates; > 50% is real directional skill.
        def _hr(subset):
            f = sum(1 for x in subset if x["grade"] == FAVORABLE)
            u = sum(1 for x in subset if x["grade"] == UNFAVORABLE)
            return (f / (f + u)) if (f + u) else None, (f + u)

        bull_hr, bull_n = _hr([x for x in graded if x["directional_bias"] == "BULLISH"])
        bear_hr, bear_n = _hr([x for x in graded if x["directional_bias"] == "BEARISH"])
        avail = [h for h in (bull_hr, bear_hr) if h is not None]
        balanced = round(sum(avail) / len(avail), 4) if avail else None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "FIXED_HORIZON_GRADER",
            "horizon_hours": self.horizon_hours,
            "tolerance_hours": self.tolerance_hours,
            "counts": counts,
            "graded_count": len(graded),
            "per_direction": {
                "bullish": {"n_decisive": bull_n, "hit_rate": round(bull_hr, 4) if bull_hr is not None else None},
                "bearish": {"n_decisive": bear_n, "hit_rate": round(bear_hr, 4) if bear_hr is not None else None},
            },
            "balanced_accuracy_precision_based": balanced,
            "skill": SkillMetricsEngine().evaluate(graded),
            "skill_note": (
                "Use skill.mcc (Matthews correlation): >0 significant = real skill, ~0 = none, "
                "<0 = anti-skill. MCC is 0 for any drift/constant predictor, so it is the "
                "drift-robust verdict. Raw hit rate is not a skill measure."
            ),
            "graded": graded,
            "status": "FIXED_HORIZON_GRADING_READY",
        }
