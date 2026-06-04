from datetime import datetime

from app.services.universe_momentum_ranking_engine import UniverseMomentumRankingEngine


class LeadershipPersistenceEngine:

    def evaluate_persistence(self):
        rankings = UniverseMomentumRankingEngine().rank_universe()
        leaders = rankings.get("rankings", [])[:10]

        persistent_leaders = []

        for index, leader in enumerate(leaders, start=1):
            symbol = leader.get("symbol")
            momentum_score = leader.get("momentum_score", 0)
            avg_pct = leader.get("average_momentum_percent", 0)

            if index <= 3 and momentum_score >= 90:
                persistence_score = 95
                persistence_state = "ELITE_LEADERSHIP_PERSISTENCE"
            elif index <= 5 and momentum_score >= 75:
                persistence_score = 82
                persistence_state = "STRONG_LEADERSHIP_PERSISTENCE"
            elif momentum_score >= 75:
                persistence_score = 70
                persistence_state = "DEVELOPING_LEADERSHIP"
            else:
                persistence_score = 50
                persistence_state = "UNCONFIRMED_LEADERSHIP"

            persistent_leaders.append({
                "rank": index,
                "symbol": symbol,
                "momentum_score": momentum_score,
                "average_momentum_percent": avg_pct,
                "leadership_persistence_score": persistence_score,
                "leadership_persistence_state": persistence_state,
                "execution_enabled": False
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "leaders_evaluated": len(persistent_leaders),
            "leaders": persistent_leaders,
            "execution_enabled": False,
            "status": "LEADERSHIP_PERSISTENCE_READY"
        }
