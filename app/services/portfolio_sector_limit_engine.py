from datetime import datetime
from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PortfolioSectorLimitEngine:

    MAX_SECTOR_PCT = 35.0

    def evaluate(self):
        exposure = PortfolioExposureEngine().evaluate()

        max_sector = exposure.get("max_sector_exposure_pct", 0)

        if max_sector >= self.MAX_SECTOR_PCT:
            state = "LIMIT_REACHED"
            multiplier = 0.0
            action = "BLOCK_SAME_SECTOR_ENTRY"
        elif max_sector >= 30:
            state = "NEAR_LIMIT"
            multiplier = 0.5
            action = "REDUCE_SAME_SECTOR_ENTRY"
        else:
            state = "AVAILABLE"
            multiplier = 1.0
            action = "NORMAL_SECTOR_DEPLOYMENT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioSectorLimitEngine",
            "max_sector_exposure_pct": max_sector,
            "sector_limit_pct": self.MAX_SECTOR_PCT,
            "sector_limit_state": state,
            "allocation_multiplier": multiplier,
            "recommended_action": action,
            "status": "PORTFOLIO_SECTOR_LIMIT_READY",
        }
