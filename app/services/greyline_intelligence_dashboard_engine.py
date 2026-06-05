from datetime import datetime

from app.services.opportunity_scoring_engine import OpportunityScoringEngine
from app.services.live_broker_health_engine import LiveBrokerHealthEngine


class GreyLineIntelligenceDashboardEngine:

    def get_dashboard(self):
        opportunity_result = OpportunityScoringEngine().score_opportunities()
        broker_health = LiveBrokerHealthEngine().evaluate()

        opportunities = opportunity_result.get("opportunities", [])

        execute_count = len([o for o in opportunities if o.get("result") == "EXECUTE"])
        watch_count = len([o for o in opportunities if o.get("result") == "WATCH"])
        reject_count = len([o for o in opportunities if o.get("result") == "REJECT"])

        top_opportunities = sorted(
            opportunities,
            key=lambda item: item.get("composite_score", 0),
            reverse=True
        )[:5]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "INTELLIGENCE_DASHBOARD_READ_ONLY",
            "broker_health": broker_health,
            "symbols_scored": opportunity_result.get("symbols_scored", 0),
            "execute_count": execute_count,
            "watch_count": watch_count,
            "reject_count": reject_count,
            "top_opportunities": top_opportunities,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "GREYLINE_INTELLIGENCE_DASHBOARD_READY"
        }
