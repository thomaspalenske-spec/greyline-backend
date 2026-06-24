from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PortfolioCorrelationEngine:

    def evaluate(self):
        exposure = PortfolioExposureEngine().evaluate()
        positions = exposure.get("positions", [])

        sector_groups = {}

        for position in positions:
            sector = position.get("sector", "UNKNOWN")

            sector_groups.setdefault(sector, []).append(
                position.get("symbol")
            )

        clusters = []

        for sector, symbols in sector_groups.items():
            if len(symbols) >= 2:
                clusters.append({
                    "theme": sector,
                    "symbols": symbols,
                    "cluster_size": len(symbols)
                })

        largest_cluster = max(
            [c["cluster_size"] for c in clusters],
            default=1
        )

        if largest_cluster >= 4:
            correlation_risk = "HIGH"
            diversification_score = 40
            action = "REDUCE_CORRELATED_CLUSTER_EXPOSURE"
        elif largest_cluster >= 3:
            correlation_risk = "ELEVATED"
            diversification_score = 65
            action = "LIMIT_ADDITIONAL_CLUSTER_EXPOSURE"
        elif largest_cluster >= 2:
            correlation_risk = "MODERATE"
            diversification_score = 80
            action = "MONITOR_CLUSTER_GROWTH"
        else:
            correlation_risk = "LOW"
            diversification_score = 95
            action = "PORTFOLIO_WELL_DIVERSIFIED"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioCorrelationEngine",
            "open_position_count": len(positions),
            "correlation_risk": correlation_risk,
            "portfolio_diversification_score": diversification_score,
            "recommended_action": action,
            "correlated_clusters": clusters,
            "status": "PORTFOLIO_CORRELATION_READY",
        }
