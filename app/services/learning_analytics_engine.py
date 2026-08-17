from datetime import datetime

from app.services.decision_learning_memory_engine import DecisionLearningMemoryEngine
from app.services.ttl_cache import ttl_cached


class LearningAnalyticsEngine:

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def summarize(self, limit=500):
        history = DecisionLearningMemoryEngine().get_history(limit=limit)
        events = history.get("events", [])

        symbol_stats = {}

        for event in events:
            symbol = event.get("symbol") or "UNKNOWN"
            adjustment = event.get("learning_adjustment")

            if symbol not in symbol_stats:
                symbol_stats[symbol] = {
                    "symbol": symbol,
                    "learning_events": 0,
                    "increase_confidence": 0,
                    "reduce_confidence": 0,
                    "hold_confidence": 0,
                    "net_confidence_drift": 0,
                    "confidence_trend": "NEUTRAL",
                }

            stats = symbol_stats[symbol]
            stats["learning_events"] += 1

            if adjustment == "INCREASE_CONFIDENCE":
                stats["increase_confidence"] += 1
                stats["net_confidence_drift"] += 1
            elif adjustment == "REDUCE_CONFIDENCE":
                stats["reduce_confidence"] += 1
                stats["net_confidence_drift"] -= 1
            else:
                stats["hold_confidence"] += 1

        symbols = []
        for stats in symbol_stats.values():
            drift = stats["net_confidence_drift"]
            if drift > 0:
                stats["confidence_trend"] = "UP"
            elif drift < 0:
                stats["confidence_trend"] = "DOWN"
            else:
                stats["confidence_trend"] = "NEUTRAL"
            symbols.append(stats)

        symbols = sorted(
            symbols,
            key=lambda item: item.get("net_confidence_drift", 0),
            reverse=True,
        )

        total_events = sum(item["learning_events"] for item in symbols)
        total_increase = sum(item["increase_confidence"] for item in symbols)
        total_reduce = sum(item["reduce_confidence"] for item in symbols)
        total_hold = sum(item["hold_confidence"] for item in symbols)

        net_confidence_drift = total_increase - total_reduce

        if net_confidence_drift > 0:
            system_confidence_trend = "UP"
        elif net_confidence_drift < 0:
            system_confidence_trend = "DOWN"
        else:
            system_confidence_trend = "NEUTRAL"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "LEARNING_ANALYTICS",
            "total_learning_events": total_events,
            "symbols_tracked": len(symbols),
            "increase_confidence_events": total_increase,
            "reduce_confidence_events": total_reduce,
            "hold_confidence_events": total_hold,
            "net_confidence_drift": net_confidence_drift,
            "system_confidence_trend": system_confidence_trend,
            "symbol_learning": symbols,
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "LEARNING_ANALYTICS_READY",
        }
