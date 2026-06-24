from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine
from app.services.portfolio_concentration_engine import PortfolioConcentrationEngine
from app.services.portfolio_correlation_engine import PortfolioCorrelationEngine
from app.services.portfolio_capacity_engine import PortfolioCapacityEngine
from app.services.portfolio_heat_engine import PortfolioHeatEngine
from app.services.portfolio_heat_engine import PortfolioHeatEngine


class PortfolioAllocationEngine:

    def evaluate(self, deployment_score=75):

        exposure = PortfolioExposureEngine().evaluate()
        concentration = PortfolioConcentrationEngine().evaluate()
        correlation = PortfolioCorrelationEngine().evaluate()
        capacity = PortfolioCapacityEngine().evaluate()
        heat = PortfolioHeatEngine().evaluate()

        base_allocation = 0

        if deployment_score >= 95:
            base_allocation = 100
        elif deployment_score >= 90:
            base_allocation = 80
        elif deployment_score >= 80:
            base_allocation = 60
        elif deployment_score >= 70:
            base_allocation = 40
        elif deployment_score >= 60:
            base_allocation = 20

        allocation = float(base_allocation)
        adjustments = []

        if concentration.get("concentration_state") == "HIGH":
            allocation *= 0.50
            adjustments.append("HIGH_CONCENTRATION_REDUCTION")

        elif concentration.get("concentration_state") == "ELEVATED":
            allocation *= 0.75
            adjustments.append("CONCENTRATION_REDUCTION")

        if correlation.get("correlation_risk") == "HIGH":
            allocation *= 0.50
            adjustments.append("HIGH_CORRELATION_REDUCTION")

        elif correlation.get("correlation_risk") == "ELEVATED":
            allocation *= 0.75
            adjustments.append("CORRELATION_REDUCTION")

        capacity_multiplier = float(capacity.get("allocation_multiplier") or 1.0)
        if capacity_multiplier < 1.0:
            allocation *= capacity_multiplier
            adjustments.append("CAPACITY_REDUCTION")

        heat_state = heat.get("heat_state")
        if heat_state == "CRITICAL":
            allocation = 0
            adjustments.append("HEAT_BLOCK")
        elif heat_state == "ELEVATED":
            allocation *= 0.50
            adjustments.append("HEAT_REDUCTION")
        elif heat_state == "MODERATE":
            allocation *= 0.75
            adjustments.append("MODERATE_HEAT_REDUCTION")

        allocation = round(allocation, 2)

        if allocation >= 60:
            state = "FULL_ALLOCATION"
        elif allocation >= 40:
            state = "APPROVED"
        elif allocation > 0:
            state = "REDUCED"
        else:
            state = "BLOCKED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioAllocationEngine",
            "deployment_score": deployment_score,
            "base_allocation_pct": base_allocation,
            "recommended_position_size_pct": allocation,
            "allocation_state": state,
            "allocation_adjustments": adjustments,
            "exposure": exposure,
            "concentration": concentration,
            "correlation": correlation,
            "capacity": capacity,
            "heat": heat,
            "status": "PORTFOLIO_ALLOCATION_READY",
        }
