from datetime import datetime


class ConfidenceCalibrationEngine:
    def evaluate(self, observations=None):
        observations = observations or []

        total = len(observations)

        wins = sum(
            1 for x in observations
            if x.get("successful")
        )

        losses = total - wins

        win_rate = (
            round((wins / total) * 100, 2)
            if total
            else 0
        )

        if win_rate >= 70:
            confidence = "HIGH"
        elif win_rate >= 55:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ConfidenceCalibrationEngine",
            "sample_size": total,
            "wins": wins,
            "losses": losses,
            "historical_win_rate_pct": win_rate,
            "confidence_level": confidence,
            "status": "CONFIDENCE_CALIBRATION_READY",
        }
