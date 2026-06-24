from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine
from app.services.portfolio_conflict_engine import PortfolioConflictEngine
from app.services.portfolio_regime_alignment_engine import PortfolioRegimeAlignmentEngine
from app.services.portfolio_directional_exposure_engine import PortfolioDirectionalExposureEngine


class PortfolioExitPrioritizationEngine:
    DEFENSIVE = {"CONSUMER_STAPLES", "UTILITIES", "HEALTHCARE"}
    CYCLICAL = {"FINANCIALS", "ENERGY", "INDUSTRIALS", "CONSUMER_DISCRETIONARY", "TECHNOLOGY"}

    def evaluate(self, regime="NEUTRAL"):
        regime = (regime or "NEUTRAL").upper().strip()

        exposure = PortfolioExposureEngine().evaluate()
        conflict = PortfolioConflictEngine().evaluate()
        regime_alignment = PortfolioRegimeAlignmentEngine().evaluate(regime=regime)
        directional = PortfolioDirectionalExposureEngine().evaluate()

        positions = exposure.get("positions", [])
        sector_exposure = exposure.get("sector_exposure", {})
        conflicts = conflict.get("conflicts", [])

        exit_candidates = []

        for pos in positions:
            symbol = pos.get("symbol")
            sector = pos.get("sector")
            reasons = []
            score = 0

            sector_pct = float(sector_exposure.get(sector, {}).get("pct_of_portfolio") or 0)

            if sector_pct >= 35:
                score += 20
                reasons.append("CONCENTRATION_CONTRIBUTOR")
            elif sector_pct >= 25:
                score += 10
                reasons.append("ELEVATED_SECTOR_EXPOSURE")

            if directional.get("directional_risk") == "HIGH" and pos.get("directional_bias") == "BULLISH":
                score += 15
                reasons.append("DIRECTIONAL_CROWDING_CONTRIBUTOR")

            for item in conflicts:
                pair = item.get("conflict_pair", [])
                if symbol in pair or symbol == item.get("existing_position"):
                    if item.get("severity") == "HIGH":
                        score += 30
                    else:
                        score += 15
                    reasons.append(item.get("conflict_type", "PORTFOLIO_CONFLICT"))

            if regime in ["RISK_OFF", "DEFENSIVE", "BEARISH"] and sector in self.CYCLICAL:
                score += 25
                reasons.append("RISK_OFF_REGIME_MISALIGNMENT")

            if regime in ["RISK_ON", "BULLISH", "EXPANSION"] and sector in self.DEFENSIVE:
                score += 25
                reasons.append("RISK_ON_REGIME_MISALIGNMENT")

            if not reasons:
                reasons.append("LOW_EXIT_PRIORITY")

            if score >= 80:
                priority = "HIGH"
                action = "REVIEW_FOR_EXIT_OR_REDUCTION"
            elif score >= 50:
                priority = "ELEVATED"
                action = "CONSIDER_REDUCTION"
            elif score >= 25:
                priority = "MODERATE"
                action = "MONITOR"
            else:
                priority = "LOW"
                action = "HOLD"

            exit_candidates.append({
                "symbol": symbol,
                "sector": sector,
                "exit_score": score,
                "exit_priority": priority,
                "recommended_action": action,
                "reasons": reasons,
            })

        exit_candidates = sorted(
            exit_candidates,
            key=lambda x: x.get("exit_score", 0),
            reverse=True,
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioExitPrioritizationEngine",
            "regime": regime,
            "exit_candidate_count": len(exit_candidates),
            "top_exit_candidate": exit_candidates[0] if exit_candidates else None,
            "exit_candidates": exit_candidates,
            "conflict": conflict,
            "regime_alignment": regime_alignment,
            "directional_exposure": directional,
            "status": "PORTFOLIO_EXIT_PRIORITIZATION_READY",
        }
