from datetime import datetime

from app.services.cross_asset_flow_engine import CrossAssetFlowEngine
from app.services.leadership_rotation_summary_engine import LeadershipRotationSummaryEngine


class RotationVelocityEngine:

    def evaluate_velocity(self):
        leadership = LeadershipRotationSummaryEngine().summarize()
        cross_asset = CrossAssetFlowEngine().evaluate_cross_asset_flow()

        top_group = cross_asset.get("top_asset_group")
        rankings = cross_asset.get("rankings", [])

        top_score = 0
        second_score = 0

        if len(rankings) >= 1:
            top_score = rankings[0].get("average_momentum_score", 0)

        if len(rankings) >= 2:
            second_score = rankings[1].get("average_momentum_score", 0)

        velocity_gap = round(top_score - second_score, 2)

        if velocity_gap >= 15:
            velocity_state = "RAPID_ROTATION"
            velocity_score = 95
        elif velocity_gap >= 8:
            velocity_state = "ACCELERATING_ROTATION"
            velocity_score = 80
        elif velocity_gap >= 3:
            velocity_state = "STEADY_ROTATION"
            velocity_score = 65
        else:
            velocity_state = "LOW_ROTATION"
            velocity_score = 50

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "leadership_state": leadership.get("rotation_state"),
            "top_asset_group": top_group,
            "velocity_gap": velocity_gap,
            "rotation_velocity_score": velocity_score,
            "rotation_velocity_state": velocity_state,
            "execution_enabled": False,
            "status": "ROTATION_VELOCITY_READY"
        }
