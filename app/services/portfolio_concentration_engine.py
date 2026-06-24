from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PortfolioConcentrationEngine:
    def evaluate(self):
        exposure = PortfolioExposureEngine().evaluate()
        sectors = exposure.get("sector_exposure") or {}

        largest_sector = None
        largest_pct = 0.0

        for sector, data in sectors.items():
            pct = float(data.get("pct_of_portfolio") or 0)
            if pct > largest_pct:
                largest_sector = sector
                largest_pct = pct

        if largest_pct >= 50:
            concentration_state = "HIGH"
            action = f"BLOCK_ADDITIONAL_{largest_sector}_EXPOSURE"
        elif largest_pct >= 35:
            concentration_state = "ELEVATED"
            action = f"LIMIT_ADDITIONAL_{largest_sector}_EXPOSURE"
        elif largest_pct >= 20:
            concentration_state = "MODERATE"
            action = "MONITOR_SECTOR_CONCENTRATION"
        else:
            concentration_state = "LOW"
            action = "NO_CONCENTRATION_ACTION_REQUIRED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioConcentrationEngine",
            "largest_sector": largest_sector,
            "largest_sector_pct": largest_pct,
            "concentration_state": concentration_state,
            "recommended_action": action,
            "exposure": exposure,
            "status": "PORTFOLIO_CONCENTRATION_READY",
        }
