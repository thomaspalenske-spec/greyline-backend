from datetime import datetime
from app.services.signal_decay_engine import SignalDecayEngine
from app.services.signal_reliability_engine import SignalReliabilityEngine


class OpportunityQueueEngine:
    def build(self, battlefield):
        rows = []

        for key, option_type in [("best_call", "CALL"), ("best_put", "PUT")]:
            item = battlefield.get(key, {}) or {}
            if not item:
                continue

            score = float(item.get("composite_score") or item.get("score") or 0)
            signal_age_days = float(item.get("signal_age_days") or item.get("age_days") or 0)
            signal_decay = SignalDecayEngine().evaluate(signal_age_days)
            adjusted_score = round(score * (signal_decay.get("signal_strength_score", 100) / 100), 2)
            signal_decay_penalty = round(score - adjusted_score, 2)
            signal_decay_reason = (
                "NO_SIGNAL_DECAY_PENALTY"
                if signal_decay_penalty <= 0
                else f"SIGNAL_DECAY_REDUCED_SCORE_BY_{signal_decay_penalty}"
            )

            raw_liquidity = item.get("liquidity_score")
            liquidity_available = raw_liquidity is not None
            liquidity = float(raw_liquidity) if liquidity_available else None

            reliability = SignalReliabilityEngine().evaluate({
                **item,
                "option_type": option_type,
                "score": adjusted_score,
                "liquidity_score": liquidity,
                "confidence": item.get("direction_confidence") or item.get("confidence") or adjusted_score,
            })

            rows.append({
                "symbol": item.get("symbol"),
                "option_type": option_type,
                "result": item.get("result"),
                "score": score,
                "adjusted_score": adjusted_score,
                "signal_decay": signal_decay,
                "signal_decay_penalty": signal_decay_penalty,
                "signal_decay_reason": signal_decay_reason,
                "liquidity_score": liquidity,
                "liquidity_status": "AVAILABLE" if liquidity_available else "UNAVAILABLE",
                "execute_score_threshold": 85,
                "execute_liquidity_threshold": 70,
                "score_distance_to_execute": round(max(85 - adjusted_score, 0), 2),
                "liquidity_distance_to_execute": round(max(70 - liquidity, 0), 2) if liquidity_available else None,
                "directional_bias": item.get("directional_bias"),
                "setup_score": item.get("setup_score"),
                "direction_confidence": item.get("direction_confidence"),
            })

        rows = sorted(
            rows,
            key=lambda x: (
                x["score_distance_to_execute"],
                x["liquidity_distance_to_execute"] if x["liquidity_distance_to_execute"] is not None else 999,
                -x["adjusted_score"],
            )
        )

        for i, row in enumerate(rows, 1):
            row["rank"] = i

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "OpportunityQueueEngine",
            "queue": rows,
            "top_candidate": rows[0] if rows else None,
            "status": "OPPORTUNITY_QUEUE_READY",
        }
