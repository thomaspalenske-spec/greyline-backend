
from datetime import datetime

from app.services.simulation.historical_opportunity_scoring_engine import HistoricalOpportunityScoringEngine


class HistoricalMasterDecisionEngine:

    def evaluate(self, symbols, simulated_time):

        opportunity_summary = HistoricalOpportunityScoringEngine().score_universe_snapshot(
            symbols,
            simulated_time
        )

        opportunities = opportunity_summary.get("opportunities", [])

        top = None

        if opportunities:
            top = sorted(
                opportunities,
                key=lambda x: x.get("composite_score",0),
                reverse=True
            )[0]

        execute = (
            top is not None and
            top.get("result") == "EXECUTE"
        )

        if execute:
            decision = "EXECUTE"

        elif top:
            decision = "WATCH"

        else:
            decision = "NO_ACTION"

        return {

            "timestamp": datetime.utcnow().isoformat(),

            "engine":"HistoricalMasterDecisionEngine",

            "simulated_time": simulated_time,

            "decision":decision,

            "candidate_available":top is not None,

            "top_candidate":top,

            "symbols_scored":len(symbols),

            "future_visible":False,

            "status":"HISTORICAL_MASTER_DECISION_READY"

        }
