from datetime import datetime
from collections import defaultdict


class RegimeLearningEngine:
    """
    Learns regime performance from graded forecast outcomes.

    This engine is read-only. It never changes calibration values directly.
    It produces learned statistics that RegimeCalibrationEngine can consume.
    """

    def evaluate(self, graded_records):
        buckets = defaultdict(list)

        for r in graded_records or []:
            state = (
                r.get("regime_calibration_state")
                or r.get("regime")
            )

            if not state:
                continue

            buckets[state].append(r)

        learning = {}

        for state, rows in buckets.items():
            total = len(rows)

            wins = sum(
                1
                for x in rows
                if x.get("forecast_correct")
            )

            win_rate = (
                wins / total
                if total
                else 0.0
            )

            returns = [
                float(x.get("return_pct") or 0)
                for x in rows
            ]

            expectancy = (
                sum(returns) / len(returns)
                if returns
                else 0.0
            )

            learning[state] = {
                "sample_size": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": round(win_rate * 100, 2),
                "expectancy_pct": round(expectancy, 2),
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "RegimeLearningEngine",
            "learning": learning,
            "status": "REGIME_LEARNING_READY",
        }
