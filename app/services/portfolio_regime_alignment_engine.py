from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PortfolioRegimeAlignmentEngine:
    DEFENSIVE = {"CONSUMER_STAPLES", "UTILITIES", "HEALTHCARE"}
    CYCLICAL = {"FINANCIALS", "ENERGY", "INDUSTRIALS", "CONSUMER_DISCRETIONARY", "TECHNOLOGY"}

    def evaluate(self, regime="NEUTRAL"):
        regime = (regime or "NEUTRAL").upper().strip()
        exposure = PortfolioExposureEngine().evaluate()
        sector_exposure = exposure.get("sector_exposure", {})

        defensive_pct = sum(
            data.get("pct_of_portfolio", 0)
            for sector, data in sector_exposure.items()
            if sector in self.DEFENSIVE
        )

        cyclical_pct = sum(
            data.get("pct_of_portfolio", 0)
            for sector, data in sector_exposure.items()
            if sector in self.CYCLICAL
        )

        if regime in ["RISK_OFF", "DEFENSIVE", "BEARISH"]:
            alignment_score = defensive_pct - (cyclical_pct * 0.5) + 50
            preferred = list(self.DEFENSIVE)
            reduce = list(self.CYCLICAL)
        elif regime in ["RISK_ON", "BULLISH", "EXPANSION"]:
            alignment_score = cyclical_pct - (defensive_pct * 0.5) + 50
            preferred = list(self.CYCLICAL)
            reduce = list(self.DEFENSIVE)
        else:
            alignment_score = 75 - abs(defensive_pct - cyclical_pct) * 0.25
            preferred = []
            reduce = []

        alignment_score = round(max(0, min(100, alignment_score)), 2)

        if alignment_score >= 80:
            state = "ALIGNED"
            multiplier = 1.1
            action = "ALLOW_NORMAL_OR_INCREASED_DEPLOYMENT"
        elif alignment_score >= 60:
            state = "PARTIAL_ALIGNMENT"
            multiplier = 1.0
            action = "NORMAL_DEPLOYMENT"
        elif alignment_score >= 40:
            state = "MISALIGNED"
            multiplier = 0.8
            action = "REDUCE_MISALIGNED_DEPLOYMENT"
        else:
            state = "SEVERELY_MISALIGNED"
            multiplier = 0.0
            action = "BLOCK_NEW_DEPLOYMENT_UNTIL_REALIGNED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioRegimeAlignmentEngine",
            "regime": regime,
            "alignment_score": alignment_score,
            "portfolio_alignment": state,
            "defensive_exposure_pct": round(defensive_pct, 2),
            "cyclical_exposure_pct": round(cyclical_pct, 2),
            "preferred_sectors": preferred,
            "sectors_to_reduce": reduce,
            "allocation_multiplier": multiplier,
            "recommended_action": action,
            "exposure": exposure,
            "status": "PORTFOLIO_REGIME_ALIGNMENT_READY",
        }
