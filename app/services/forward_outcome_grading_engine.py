from datetime import datetime


class ForwardOutcomeGradingEngine:
    # Returns inside this band are indistinguishable from noise and from the cost of
    # trading, so they are FLAT rather than a win. Testing `== 0` meant a move of
    # +0.00006% rounded to 0.0001 and graded C (a win) while +0.00004% graded FLAT — a
    # rounding artifact deciding a directional verdict.
    FLAT_BAND_PCT = 0.01

    def _grade(self, directional_return_pct):
        if directional_return_pct >= 3:
            return "A"
        if directional_return_pct >= 1:
            return "B"
        if abs(directional_return_pct) < self.FLAT_BAND_PCT:
            return "FLAT"
        if directional_return_pct > 0:
            return "C"
        return "F"

    def grade(self, predictions):
        graded = []
        skipped_unmatured = 0

        for item in predictions or []:
            snapshot = float(item.get("snapshot_price") or 0)
            # Score against the T+horizon price, NOT the live quote. `current_price` is
            # whatever the market was doing when the capture ran, so grading on it gave an
            # undefined holding period — an A on a 90-second-old decision and an A on a
            # six-hour-old one pooled into the same bucket.
            outcome = float(item.get("outcome_price") or 0)
            bias = item.get("directional_bias")

            if outcome <= 0:
                skipped_unmatured += 1
                continue
            if snapshot <= 0 or bias not in ["BULLISH", "BEARISH"]:
                continue
            current = outcome

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

        # None, not 0, with nothing graded: "no measurement" and "measured breakeven" were
        # the same output, next to a READY status.
        avg_directional_return = (
            round(sum(x.get("directional_return_pct", 0) for x in graded) / len(graded), 4)
            if graded else None
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
