from datetime import datetime


class OpportunitySymmetryEngine:
    def evaluate(self, opportunities=None):
        opportunities = opportunities or []

        bullish = []
        bearish = []
        neutral = []
        unknown = []

        for item in opportunities:
            direction = self._direction(item)
            normalized = dict(item)
            normalized["symmetry_direction"] = direction

            if direction == "BULLISH":
                bullish.append(normalized)
            elif direction == "BEARISH":
                bearish.append(normalized)
            elif direction == "NEUTRAL":
                neutral.append(normalized)
            else:
                unknown.append(normalized)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "OpportunitySymmetryEngine",
            "bull_scan_complete": True,
            "bear_scan_complete": True,
            "bullish_candidates": len(bullish),
            "bearish_candidates": len(bearish),
            "neutral_candidates": len(neutral),
            "unknown_direction_candidates": len(unknown),
            "bullish_watch": self._count_result(bullish, "WATCH"),
            "bearish_watch": self._count_result(bearish, "WATCH"),
            "bullish_execute": self._count_result(bullish, "EXECUTE"),
            "bearish_execute": self._count_result(bearish, "EXECUTE"),
            "bullish_avg_score": self._avg_score(bullish),
            "bearish_avg_score": self._avg_score(bearish),
            "opportunity_bias": self._bias(len(bullish), len(bearish)),
            "status": "OPPORTUNITY_SYMMETRY_EVALUATED",
        }

    def _direction(self, item):
        fields = [
            item.get("direction"),
            item.get("side"),
            item.get("bias"),
            item.get("signal"),
            item.get("option_type"),
            item.get("contract_type"),
            item.get("strategy"),
            item.get("trade_type"),
            item.get("result"),
        ]

        text = " ".join([str(x).upper() for x in fields if x is not None])

        if any(x in text for x in ["PUT", "SHORT", "SELL", "BEAR", "BEARISH", "DOWNSIDE"]):
            return "BEARISH"

        if any(x in text for x in ["CALL", "LONG", "BUY", "BULL", "BULLISH", "UPSIDE", "EXECUTE"]):
            return "BULLISH"

        if any(x in text for x in ["NEUTRAL", "IRON", "CONDOR", "STRADDLE", "STRANGLE"]):
            return "NEUTRAL"

        return "UNKNOWN"

    def _count_result(self, items, result):
        return len([
            item for item in items
            if result in str(item.get("result") or item.get("state") or item.get("decision") or "").upper()
        ])

    def _avg_score(self, items):
        scores = [
            float(item.get("composite_score", 0))
            for item in items
            if item.get("composite_score") is not None
        ]
        if not scores:
            return 0
        return round(sum(scores) / len(scores), 2)

    def _bias(self, bullish_count, bearish_count):
        total = bullish_count + bearish_count

        if total == 0:
            return "NO_DIRECTIONAL_DATA"

        bullish_pct = bullish_count / total
        bearish_pct = bearish_count / total

        if bullish_pct >= 0.75:
            return "BULLISH_BIAS_DETECTED"

        if bearish_pct >= 0.75:
            return "BEARISH_BIAS_DETECTED"

        return "BALANCED"
