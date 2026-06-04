from datetime import datetime

from app.services.universe_snapshot_reader import UniverseSnapshotReader
from app.services.historical_momentum_engine import HistoricalMomentumEngine


class UniverseMomentumRankingEngine:

    def rank_universe(self):
        coverage = UniverseSnapshotReader().read_snapshot_coverage()
        symbols = list(coverage.get("coverage", {}).keys())

        rankings = []

        for symbol in symbols:
            momentum = HistoricalMomentumEngine().calculate_momentum(symbol)

            rankings.append({
                "symbol": symbol,
                "momentum_available": momentum.get("momentum_available"),
                "valid_price_points": momentum.get("valid_price_points"),
                "latest_price": momentum.get("latest_price"),
                "previous_price": momentum.get("previous_price"),
                "percent_change": momentum.get("percent_change"),
                "momentum_score": momentum.get("momentum_score", 0),
                "momentum_state": momentum.get("momentum_state"),
                "execution_enabled": False
            })

        rankings.sort(
            key=lambda item: item.get("momentum_score", 0),
            reverse=True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_ranked": len(rankings),
            "rankings": rankings,
            "execution_enabled": False,
            "status": "UNIVERSE_MOMENTUM_RANKING_READY"
        }
