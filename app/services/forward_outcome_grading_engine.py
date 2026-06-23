from datetime import datetime


class ForwardOutcomeGradingEngine:
    def _grade(self, directional_return_pct):
        if directional_return_pct >= 3:
            return "A"
        if directional_return_pct >= 1:
            return "B"
        if directional_return_pct > 0:
            return "C"
        if directional_return_pct == 0:
            return "FLAT"
        return "F"

    def grade(self, predictions):
        graded = []

        for item in predictions or []:
            snapshot = float(item.get("snapshot_price") or 0)
            current = float(item.get("current_price") or 0)
            bias = item.get("directional_bias")

            if snapshot <= 0 or current <= 0 or bias not in ["BULLISH", "BEARISH"]:
                continue

            raw_return_pct = round(((current / snapshot) - 1) * 100, 4)
            directional_return_pct = raw_return_pct if bias == "BULLISH" else round(raw_return_pct * -1, 4)

            graded.append({
                "symbol": item.get("symbol"),
                "directional_bias": bias,
                "candidate_result": item.get("candidate_result"),
                "snapshot_price": snapshot,
                "current_price": current,
                "raw_return_pct": raw_return_pct,
                "directional_return_pct": directional_return_pct,
                "grade": self._grade(directional_return_pct),
            })

        grade_counts = {}
        for item in graded:
            grade = item.get("grade")
            grade_counts[grade] = grade_counts.get(grade, 0) + 1

        avg_directional_return = (
            round(sum(x.get("directional_return_pct", 0) for x in graded) / len(graded), 4)
            if graded else 0
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeGradingEngine",
            "graded_predictions": len(graded),
            "average_directional_return_pct": avg_directional_return,
            "grade_counts": grade_counts,
            "grades": graded[-25:],
            "status": "FORWARD_OUTCOME_GRADING_READY",
        }
