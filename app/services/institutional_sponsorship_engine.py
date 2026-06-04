from datetime import datetime

from app.services.institutional_accumulation_engine import InstitutionalAccumulationEngine
from app.services.leadership_persistence_engine import LeadershipPersistenceEngine


class InstitutionalSponsorshipEngine:

    def evaluate_symbol(self, symbol):
        symbol = symbol.upper().strip()

        accumulation = InstitutionalAccumulationEngine().evaluate_symbol(symbol)

        leadership = LeadershipPersistenceEngine().evaluate_persistence()

        persistence_score = 50

        for leader in leadership.get("leaders", []):
            if leader.get("symbol") == symbol:
                persistence_score = leader.get(
                    "leadership_persistence_score",
                    50
                )
                break

        accumulation_score = accumulation.get(
            "accumulation_score",
            50
        )

        sponsorship_score = round(
            (accumulation_score * 0.60) +
            (persistence_score * 0.40),
            2
        )

        if sponsorship_score >= 90:
            sponsorship_state = "HEAVY_INSTITUTIONAL_SPONSORSHIP"
        elif sponsorship_score >= 75:
            sponsorship_state = "STRONG_INSTITUTIONAL_SPONSORSHIP"
        elif sponsorship_score >= 60:
            sponsorship_state = "DEVELOPING_SPONSORSHIP"
        else:
            sponsorship_state = "LIMITED_SPONSORSHIP"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "accumulation_score": accumulation_score,
            "leadership_persistence_score": persistence_score,
            "institutional_sponsorship_score": sponsorship_score,
            "institutional_sponsorship_state": sponsorship_state,
            "execution_enabled": False,
            "status": "INSTITUTIONAL_SPONSORSHIP_READY"
        }
