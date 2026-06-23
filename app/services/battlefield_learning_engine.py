from datetime import datetime


class BattlefieldLearningEngine:
    def _bucket_average(self, rows):
        if not rows:
            return 0
        return round(
            sum(float(x.get("directional_return_pct") or 0) for x in rows) / len(rows),
            4
        )

    def evaluate(self, grades):
        rows = grades or []

        by_symbol = {}
        by_direction = {}
        by_result = {}

        for item in rows:
            symbol = item.get("symbol") or "UNKNOWN"
            direction = item.get("directional_bias") or "UNKNOWN"
            result = item.get("candidate_result") or "UNKNOWN"

            by_symbol.setdefault(symbol, []).append(item)
            by_direction.setdefault(direction, []).append(item)
            by_result.setdefault(result, []).append(item)

        symbol_scores = [
            {
                "symbol": symbol,
                "samples": len(items),
                "average_directional_return_pct": self._bucket_average(items),
            }
            for symbol, items in by_symbol.items()
        ]

        direction_scores = [
            {
                "direction": direction,
                "samples": len(items),
                "average_directional_return_pct": self._bucket_average(items),
            }
            for direction, items in by_direction.items()
        ]

        result_scores = [
            {
                "candidate_result": result,
                "samples": len(items),
                "average_directional_return_pct": self._bucket_average(items),
            }
            for result, items in by_result.items()
        ]

        symbol_scores = sorted(symbol_scores, key=lambda x: x["average_directional_return_pct"], reverse=True)
        direction_scores = sorted(direction_scores, key=lambda x: x["average_directional_return_pct"], reverse=True)
        result_scores = sorted(result_scores, key=lambda x: x["average_directional_return_pct"], reverse=True)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BattlefieldLearningEngine",
            "learning_state": "ACTIVE" if rows else "INSUFFICIENT_DATA",
            "sample_count": len(rows),
            "top_performing_symbols": symbol_scores[:5],
            "worst_performing_symbols": symbol_scores[-5:],
            "direction_performance": direction_scores,
            "candidate_result_performance": result_scores,
            "status": "BATTLEFIELD_LEARNING_READY",
        }
