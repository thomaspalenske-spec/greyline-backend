from datetime import datetime


class GreyLineStrategyExecutionRouterEngine:

    def route(self, regime_result):

        regime = regime_result.get("regime")

        base_weights = {}

        # Multi-strategy blending logic (not single selection anymore)
        if regime == "TREND_UP":
            base_weights = {
                "MOMENTUM": 0.5,
                "BREAKOUT_FOLLOW": 0.3,
                "MEAN_REVERSION": 0.2
            }

        elif regime == "TREND_DOWN":
            base_weights = {
                "DEFENSIVE": 0.5,
                "SHORT_BIAS": 0.3,
                "MEAN_REVERSION": 0.2
            }

        elif regime == "CHOPPY":
            base_weights = {
                "MEAN_REVERSION": 0.5,
                "SCALPING": 0.4,
                "MOMENTUM": 0.1
            }

        else:
            base_weights = {
                "BALANCED": 1.0
            }

        # Normalize (safety layer)
        total = sum(base_weights.values())
        normalized = {
            k: round(v / total, 4)
            for k, v in base_weights.items()
        }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "regime": regime,
            "strategy_weights": normalized,
            "dominant_strategy": max(normalized, key=normalized.get),
            "status": "STRATEGY_ROUTING_COMPLETE"
        }
