from datetime import datetime


class PutReadinessGateEngine:
    def evaluate(self, candidate=None):
        candidate = candidate or {}

        checks = {
            "is_put": candidate.get("option_type") == "PUT",
            "is_bearish": candidate.get("directional_bias") == "BEARISH",
            "score_ready": float(candidate.get("composite_score") or 0) >= 85,
            "confidence_ready": float(candidate.get("direction_confidence") or 0) >= 5,
            "liquidity_ready": float(candidate.get("liquidity_score") or 0) >= 70,
            "setup_ready": float(candidate.get("setup_score") or 0) >= 60,
            "watch_or_execute": candidate.get("result") in ["WATCH", "EXECUTE"],
        }

        blockers = [name for name, passed in checks.items() if not passed]

        ready = len(blockers) == 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PutReadinessGateEngine",
            "symbol": candidate.get("symbol"),
            "put_ready_for_execute": ready,
            "checks": checks,
            "blockers": blockers,
            "score": candidate.get("composite_score"),
            "bearish_score": candidate.get("bearish_score"),
            "bullish_score": candidate.get("bullish_score"),
            "direction_confidence": candidate.get("direction_confidence"),
            "status": "PUT_READY" if ready else "PUT_NOT_READY",
        }
