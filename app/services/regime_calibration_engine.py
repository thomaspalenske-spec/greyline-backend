from datetime import datetime

from app.services.forecast_regime_trust_engine import (
    ForecastRegimeTrustEngine,
)


class RegimeCalibrationEngine:
    """
    Converts learned regime performance into governed
    confidence, composite-score, execution, and sizing controls.
    """

    MINIMUM_SAMPLE_SIZE = 20

    def evaluate(self, regime: str):
        regime = (regime or "UNKNOWN").upper().strip()

        trust = (
            ForecastRegimeTrustEngine()
            .evaluate()
            .get("regimes", {})
            .get(regime, {})
        )

        sample = int(trust.get("sample_size") or 0)
        bayes = trust.get("bayesian_accuracy_pct")

        calibration = {
            "confidence_adjustment": 0.0,
            "composite_adjustment": 0.0,
            "position_multiplier": 1.0,
            "execution_allowed": True,
            "state": "LEARNING",
        }

        actionable = (
            regime != "UNKNOWN"
            and sample >= self.MINIMUM_SAMPLE_SIZE
            and bayes is not None
        )

        if regime == "UNKNOWN":
            calibration.update({
                "state": "UNKNOWN_REGIME",
                "execution_allowed": True,
            })

        elif not actionable:
            calibration.update({
                "state": "LEARNING",
                "execution_allowed": True,
            })

        elif bayes >= 80:
            calibration.update({
                "confidence_adjustment": 3.0,
                "composite_adjustment": 2.0,
                "position_multiplier": 1.20,
                "execution_allowed": True,
                "state": "ACCELERATE",
            })

        elif bayes >= 70:
            calibration.update({
                "confidence_adjustment": 2.0,
                "composite_adjustment": 1.0,
                "position_multiplier": 1.10,
                "execution_allowed": True,
                "state": "FAVORABLE",
            })

        elif bayes >= 60:
            calibration.update({
                "state": "NEUTRAL",
                "execution_allowed": True,
            })

        elif bayes >= 50:
            calibration.update({
                "confidence_adjustment": -2.0,
                "composite_adjustment": -1.0,
                "position_multiplier": 0.80,
                "execution_allowed": True,
                "state": "CAUTION",
            })

        else:
            calibration.update({
                "confidence_adjustment": -5.0,
                "composite_adjustment": -3.0,
                "position_multiplier": 0.50,
                "execution_allowed": False,
                "state": "NEGATIVE_EDGE",
            })

        calibration.update({
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "RegimeCalibrationEngine",
            "regime": regime,
            "sample_size": sample,
            "minimum_sample_size": self.MINIMUM_SAMPLE_SIZE,
            "bayesian_accuracy_pct": bayes,
            "credible_interval_95": trust.get(
                "credible_interval_95"
            ),
            "actionable": actionable,
            "execution_impact": (
                "REGIME_CALIBRATION_ACTIVE"
                if actionable
                else "OBSERVATION_ONLY"
            ),
            "status": "REGIME_CALIBRATION_READY",
        })

        return calibration
