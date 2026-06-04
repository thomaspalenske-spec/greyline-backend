from datetime import datetime

from app.services.leadership_persistence_engine import LeadershipPersistenceEngine


class LeadershipRotationSummaryEngine:

    def summarize(self):
        persistence = LeadershipPersistenceEngine().evaluate_persistence()

        leaders = persistence.get("leaders", [])

        elite = [
            leader for leader in leaders
            if leader.get("leadership_persistence_score", 0) >= 90
        ]

        strong = [
            leader for leader in leaders
            if 80 <= leader.get("leadership_persistence_score", 0) < 90
        ]

        developing = [
            leader for leader in leaders
            if 70 <= leader.get("leadership_persistence_score", 0) < 80
        ]

        top_leader = leaders[0]["symbol"] if leaders else None

        if len(elite) >= 3:
            rotation_state = "CONCENTRATED_INSTITUTIONAL_LEADERSHIP"
        elif len(elite) >= 1:
            rotation_state = "LEADERSHIP_EMERGING"
        elif len(strong) >= 3:
            rotation_state = "ROTATION_DEVELOPING"
        else:
            rotation_state = "NO_CLEAR_LEADERSHIP"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "top_leader": top_leader,
            "elite_leaders": [x["symbol"] for x in elite],
            "strong_leaders": [x["symbol"] for x in strong],
            "developing_leaders": [x["symbol"] for x in developing],
            "rotation_state": rotation_state,
            "execution_enabled": False,
            "status": "LEADERSHIP_ROTATION_SUMMARY_READY"
        }
