from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PortfolioCapacityEngine:

    def evaluate(self):
        exposure = PortfolioExposureEngine().evaluate()

        open_positions = exposure.get("open_position_count", 0)

        max_positions = 10

        capacity_used_pct = round(
            (open_positions / max_positions) * 100,
            2
        )

        if open_positions >= 10:
            state = "FULL"
            multiplier = 0.0
            action = "BLOCK_NEW_POSITIONS"

        elif open_positions >= 8:
            state = "CRITICAL"
            multiplier = 0.50
            action = "HEAVILY_REDUCE_NEW_ALLOCATION"

        elif open_positions >= 5:
            state = "ELEVATED"
            multiplier = 0.75
            action = "REDUCE_NEW_ALLOCATION"

        else:
            state = "HEALTHY"
            multiplier = 1.0
            action = "NORMAL_DEPLOYMENT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioCapacityEngine",
            "open_positions": open_positions,
            "max_positions": max_positions,
            "capacity_used_pct": capacity_used_pct,
            "capacity_remaining": max_positions - open_positions,
            "capacity_state": state,
            "allocation_multiplier": multiplier,
            "recommended_action": action,
            "status": "PORTFOLIO_CAPACITY_READY",
        }
