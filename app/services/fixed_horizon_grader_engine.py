from datetime import datetime, timedelta
from os import getenv
from pathlib import Path

from app.services.persistence.json_store import read_jsonl
from app.services.price_history_store import PriceHistoryStore, _parse
from app.services.skill_metrics_engine import MIN_SAMPLE, SkillMetricsEngine

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
        # Tolerance must stay strictly below the horizon. At tolerance >= horizon the
        # accepted window reaches back past the decision itself, so a "forward" price could
        # predate the decision and grade it against its own snapshot. The default of
        # horizon/4 is safe, but the constructor and the env var both accept overrides.
        if self.tolerance_hours >= self.horizon_hours:
            raise ValueError(
                f"tolerance_hours ({self.tolerance_hours}) must be < horizon_hours "
                f"({self.horizon_hours}); otherwise the forward price can precede the decision"
            )
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

    def _price_at(self, index, symbol, target_dt, after=None):
        """Price near `target_dt`. `after`, when given, requires the point to be at or
        after it — used to guarantee a forward price genuinely follows its decision."""
        pts = index.get(str(symbol).upper())
        if not pts:
            return None
        if after is not None:
            pts = [p for p in pts if p[0] >= after]
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
        # PENDING used to absorb three different things: a decision too young to grade, a
        # malformed record, and a symbol with no forward price. A ledger systematically
        # broken for some class of symbol therefore reported as merely immature, and if
        # that breakage correlates with symbol or regime the graded subset is a biased
        # sample of the decisions — invisible in the output. Counted separately now.
        malformed = 0
        no_forward_price = 0
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
                malformed += 1
                counts[PENDING] += 1
                continue

            # `after=ts` guarantees the forward price genuinely follows the decision. The
            # match was two-sided, so with a large enough tolerance a decision could be
            # graded against a price recorded before it was made.
            fwd = self._price_at(index, symbol, ts + horizon, after=ts)
            if not fwd:
                no_forward_price += 1
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
                "day": ts.date().isoformat(),
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

        # Independence. Rows are NOT independent observations: the same symbol is re-graded
        # every scheduler cycle over overlapping forward windows, and all symbols in one
        # cycle share a single market move. The honest unit is a distinct symbol-day.
        effective_n = len({(x["symbol"], x["day"]) for x in graded
                           if x["grade"] in (FAVORABLE, UNFAVORABLE)})

        # The headline hit rates are suppressed below the same minimum the skill verdict
        # enforces. They were previously computed unconditionally, so a payload could carry
        # hit_rate 1.0 next to verdict INSUFFICIENT_DATA, and any dashboard reading the
        # headline saw a 100% edge on one observation.
        under_min = effective_n < MIN_SAMPLE
        if under_min:
            bull_hr = bear_hr = balanced = None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "FIXED_HORIZON_GRADER",
            "horizon_hours": self.horizon_hours,
            "tolerance_hours": self.tolerance_hours,
            "counts": counts,
            # PENDING split into its real causes.
            "pending_breakdown": {
                "malformed_record": malformed,
                "no_forward_price_yet": no_forward_price,
            },
            "graded_count": len(graded),
            "effective_n_symbol_days": effective_n,
            "suppressed_below_min_sample": under_min,
            "per_direction": {
                "bullish": {"n_decisive": bull_n, "hit_rate": round(bull_hr, 4) if bull_hr is not None else None},
                "bearish": {"n_decisive": bear_n, "hit_rate": round(bear_hr, 4) if bear_hr is not None else None},
            },
            # Mean of per-direction PRECISIONS (P(correct | predicted X)), not balanced
            # accuracy, which averages recalls. The two coincide only when the predictor's
            # bullish/bearish split is balanced; a predictor skewed toward the trending
            # direction reads above 0.5 here with no discriminative skill. Use skill.mcc
            # and skill.balanced_accuracy for the drift-robust answer — this field is
            # retained for continuity and is deliberately not the one to trust.
            "mean_per_direction_precision": balanced,
            "balanced_accuracy_precision_based": balanced,   # deprecated alias, misnamed
            "skill": SkillMetricsEngine().evaluate(graded, effective_n=effective_n),
            "skill_note": (
                "Use skill.mcc (Matthews correlation): >0 significant = real skill, ~0 = none, "
                "<0 = anti-skill. MCC is 0 for any drift/constant predictor, so it is the "
                "drift-robust verdict. Raw hit rate is not a skill measure."
            ),
            "graded": graded,
            "status": "FIXED_HORIZON_GRADING_READY",
        }
