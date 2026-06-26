from datetime import datetime

from app.services.simulation.market_replay_engine import MarketReplayEngine
from app.services.simulation.historical_component_builder import HistoricalComponentBuilder
from app.services.simulation.greyline_simulation_decision_adapter import GreyLineSimulationDecisionAdapter


class HistoricalOpportunityScoringEngine:
    """
    Simulator-only opportunity scoring layer.

    Purpose:
      Produce GreyLine-style opportunity lists from historical replay snapshots.

    Rule:
      Simulator adapts to GreyLine.
      Production GreyLine engines are not modified for simulation.
    """

    def score_snapshot(self, symbol, timestamp):
        replay = MarketReplayEngine(symbol, timestamp, timestamp)
        snapshot = replay.next()

        market_data = snapshot.get("market_data") if snapshot else None
        components = HistoricalComponentBuilder().build(market_data)
        candidate = GreyLineSimulationDecisionAdapter().evaluate(market_data, components)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HistoricalOpportunityScoringEngine",
            "simulated_time": timestamp,
            "symbol": symbol,
            "market_data": market_data,
            "components": components,
            "opportunity": candidate,
            "future_visible": False,
            "status": "HISTORICAL_OPPORTUNITY_SCORE_READY",
        }

    def score_universe_snapshot(self, symbols, timestamp, limit=None):
        symbols = symbols or []
        if limit is not None:
            symbols = symbols[:limit]

        opportunities = []

        for symbol in symbols:
            result = self.score_snapshot(symbol, timestamp)
            opp = result.get("opportunity") or {}
            if opp.get("candidate_available"):
                opportunities.append(opp)

        opportunities = sorted(
            opportunities,
            key=lambda x: x.get("composite_score", 0),
            reverse=True
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HistoricalOpportunityScoringEngine",
            "simulated_time": timestamp,
            "symbols_scored": len(symbols),
            "opportunity_count": len(opportunities),
            "opportunities": opportunities,
            "top_candidate": opportunities[0] if opportunities else None,
            "execute_count": len([o for o in opportunities if o.get("result") == "EXECUTE"]),
            "watch_count": len([o for o in opportunities if o.get("result") == "WATCH"]),
            "reject_count": len([o for o in opportunities if o.get("result") == "REJECT"]),
            "future_visible": False,
            "emulation_rule": "SIMULATOR_ADAPTS_TO_GREYLINE_OPPORTUNITY_FORMAT",
            "status": "HISTORICAL_OPPORTUNITY_UNIVERSE_READY",
        }
