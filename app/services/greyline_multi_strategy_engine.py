from datetime import datetime


class GreyLineMultiStrategyEngine:

    def evaluate(self, regime_result):

        regime = regime_result.get("regime")

        strategies = []

        if regime == "TREND_UP":
            strategies = ["MOMENTUM", "BREAKOUT_FOLLOW"]
        elif regime == "TREND_DOWN":
            strategies = ["DEFENSIVE", "SHORT_BIAS"]
        elif regime == "CHOPPY":
            strategies = ["MEAN_REVERSION", "SCALPING"]
        else:
            strategies = ["BALANCED"]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "regime": regime,
            "active_strategies": strategies,
            "status": "MULTI_STRATEGY_SELECTED"
        }
