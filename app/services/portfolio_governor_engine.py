from datetime import datetime

from app.services.portfolio_allocation_engine import PortfolioAllocationEngine
from app.services.portfolio_regime_alignment_engine import PortfolioRegimeAlignmentEngine


class PortfolioGovernorEngine:
    def evaluate(self, deployment_score=0, candidate_symbol=None):
        allocation = PortfolioAllocationEngine().evaluate(deployment_score=deployment_score)
        regime_alignment = PortfolioRegimeAlignmentEngine().evaluate(regime="NEUTRAL")

        recommended_size = float(allocation.get("recommended_position_size_pct") or 0)
        adjustments = allocation.get("allocation_adjustments", [])

        concentration = allocation.get("concentration", {})
        correlation = allocation.get("correlation", {})
        capacity = allocation.get("capacity", {})
        heat = allocation.get("heat", {})
        directional = allocation.get("directional_exposure", {})
        conflict = allocation.get("conflict", {})
        regime_multiplier = float(regime_alignment.get("allocation_multiplier") or 1.0)

        if regime_multiplier < 1.0:
            recommended_size = round(recommended_size * regime_multiplier, 2)
        elif regime_multiplier > 1.0:
            recommended_size = round(min(100, recommended_size * regime_multiplier), 2)

        blockers = []
        warnings = []

        if recommended_size <= 0:
            blockers.append("ALLOCATION_ZERO")

        if capacity.get("capacity_state") == "FULL":
            blockers.append("PORTFOLIO_CAPACITY_FULL")

        if heat.get("heat_state") == "MAXED":
            blockers.append("PORTFOLIO_HEAT_MAXED")

        if conflict.get("conflict_state") == "HIGH":
            warnings.append("HIGH_PORTFOLIO_CONFLICT")

        if regime_alignment.get("portfolio_alignment") == "SEVERELY_MISALIGNED":
            blockers.append("PORTFOLIO_REGIME_SEVERELY_MISALIGNED")
        elif regime_alignment.get("portfolio_alignment") == "MISALIGNED":
            warnings.append("PORTFOLIO_REGIME_MISALIGNED")

        if directional.get("directional_risk") == "HIGH":
            warnings.append("HIGH_DIRECTIONAL_EXPOSURE")

        if concentration.get("concentration_state") in ["ELEVATED", "HIGH"]:
            warnings.append("SECTOR_CONCENTRATION_ELEVATED")

        if correlation.get("correlation_risk") == "HIGH":
            warnings.append("HIGH_CORRELATION_RISK")

        if blockers:
            decision = "BLOCK"
            new_trade_allowed = False
            max_deployment_pct = 0
            reason = "PORTFOLIO_BLOCKERS_PRESENT"
        elif recommended_size < 25:
            decision = "REDUCE"
            new_trade_allowed = True
            max_deployment_pct = recommended_size
            reason = "PORTFOLIO_RISK_REDUCED_SIZE"
        else:
            decision = "APPROVE"
            new_trade_allowed = True
            max_deployment_pct = recommended_size
            reason = "PORTFOLIO_DEPLOYMENT_APPROVED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioGovernorEngine",
            "candidate_symbol": candidate_symbol,
            "deployment_score": deployment_score,
            "portfolio_decision": decision,
            "new_trade_allowed": new_trade_allowed,
            "max_deployment_pct": round(max_deployment_pct, 2),
            "recommended_position_size_pct": recommended_size,
            "reason": reason,
            "blockers": blockers,
            "warnings": warnings,
            "allocation_adjustments": adjustments,
            "regime_alignment": regime_alignment,
            "allocation": allocation,
            "status": "PORTFOLIO_GOVERNOR_READY",
        }
