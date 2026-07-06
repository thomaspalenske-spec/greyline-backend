from datetime import datetime

from app.services.forward_outcome_capture_engine import ForwardOutcomeCaptureEngine
from app.services.forward_outcome_attribution_engine import ForwardOutcomeAttributionEngine


class BearishSignalGovernorEngine:
    def evaluate(self, limit=100):
        capture = ForwardOutcomeCaptureEngine().capture(limit=limit)
        attribution = ForwardOutcomeAttributionEngine().evaluate(
            capture.get("outcomes", [])
        )

        bearish = next(
            (
                x for x in attribution.get("direction_attribution", [])
                if x.get("directional_bias") == "BEARISH"
            ),
            {},
        )

        put = next(
            (
                x for x in attribution.get("option_type_attribution", [])
                if x.get("option_type") == "PUT"
            ),
            {},
        )

        bearish_observations = int(bearish.get("observations") or 0)
        bearish_win_rate = float(bearish.get("win_rate_pct") or 0)
        bearish_avg_return = float(bearish.get("average_directional_return_pct") or 0)

        put_observations = int(put.get("observations") or 0)
        put_win_rate = float(put.get("win_rate_pct") or 0)
        put_avg_return = float(put.get("average_directional_return_pct") or 0)

        if bearish_observations < 20 or put_observations < 20:
            state = "INSUFFICIENT_BEARISH_SAMPLE"
            action = "HOLD_CURRENT_PUT_THRESHOLDS"
            threshold_modifier = 0
            reason = "Not enough bearish/put forward outcomes to govern thresholds."
        elif bearish_win_rate < 45 or put_win_rate < 45 or bearish_avg_return < 0 or put_avg_return < 0:
            state = "BEARISH_SIGNAL_UNDERPERFORMING"
            action = "TIGHTEN_PUT_EXECUTION_THRESHOLDS"
            threshold_modifier = 5
            reason = "Bearish/put forward outcomes are underperforming live attribution."
        else:
            state = "BEARISH_SIGNAL_HEALTHY"
            action = "ALLOW_STANDARD_PUT_THRESHOLDS"
            threshold_modifier = 0
            reason = "Bearish/put forward outcomes are acceptable."

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "BearishSignalGovernorEngine",
            "sample_limit": limit,
            "bearish_observations": bearish_observations,
            "bearish_win_rate_pct": bearish_win_rate,
            "bearish_average_directional_return_pct": bearish_avg_return,
            "put_observations": put_observations,
            "put_win_rate_pct": put_win_rate,
            "put_average_directional_return_pct": put_avg_return,
            "governor_state": state,
            "recommended_action": action,
            "recommended_put_threshold_modifier": threshold_modifier,
            "reason": reason,
            "automatic_execution_changes_enabled": False,
            "human_approval_required": True,
            "status": "BEARISH_SIGNAL_GOVERNOR_READY",
        }
