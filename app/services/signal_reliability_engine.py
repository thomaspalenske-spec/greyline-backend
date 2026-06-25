from datetime import datetime


class SignalReliabilityEngine:
    def evaluate(self, candidate=None, calibration=None, data_quality=None):
        candidate = candidate or {}
        calibration = calibration or {}
        data_quality = data_quality or {}

        score = float(candidate.get("score") or candidate.get("composite_score") or 0)
        liquidity = float(candidate.get("liquidity_score") or 0)
        confidence = float(candidate.get("confidence") or score)

        freshness = float(data_quality.get("freshness_score") or 100)
        calibration_score = float(calibration.get("calibration_score") or confidence)

        reliability = (
            score * 0.35
            + liquidity * 0.20
            + confidence * 0.20
            + freshness * 0.15
            + calibration_score * 0.10
        )

        reliability = round(max(0, min(100, reliability)), 2)

        if reliability >= 90:
            grade = "A"
        elif reliability >= 80:
            grade = "B"
        elif reliability >= 70:
            grade = "C"
        elif reliability >= 60:
            grade = "D"
        else:
            grade = "F"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SignalReliabilityEngine",
            "symbol": candidate.get("symbol"),
            "option_type": candidate.get("option_type"),
            "signal_score": score,
            "signal_reliability_score": reliability,
            "signal_reliability_grade": grade,
            "reliability_inputs": {
                "score": score,
                "liquidity": liquidity,
                "confidence": confidence,
                "freshness": freshness,
                "calibration_score": calibration_score,
            },
            "status": "SIGNAL_RELIABILITY_READY",
        }
