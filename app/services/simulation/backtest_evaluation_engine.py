from datetime import datetime


class BacktestEvaluationEngine:
    """
    Converts simulator/replay events into objective performance metrics.
    Safe first version: evaluates candidate availability, signal counts, and basic quality stats.
    """

    def evaluate(self, events):
        events = events or []

        total_steps = len(events)
        candidate_events = [e for e in events if e.get("candidate_available")]
        no_candidate_events = [e for e in events if not e.get("candidate_available")]

        execute_events = [e for e in events if str(e.get("result", "")).upper() == "EXECUTE"]
        watch_events = [e for e in events if str(e.get("result", "")).upper() == "WATCH"]
        reject_events = [e for e in events if str(e.get("result", "")).upper() == "REJECT"]

        scores = [
            float(e.get("score") or e.get("composite_score") or 0)
            for e in candidate_events
        ]

        avg_score = round(sum(scores) / len(scores), 2) if scores else 0
        max_score = round(max(scores), 2) if scores else 0
        min_score = round(min(scores), 2) if scores else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BacktestEvaluationEngine",
            "total_steps": total_steps,
            "candidate_count": len(candidate_events),
            "no_candidate_count": len(no_candidate_events),
            "candidate_rate_pct": round((len(candidate_events) / total_steps) * 100, 2) if total_steps else 0,
            "execute_count": len(execute_events),
            "watch_count": len(watch_events),
            "reject_count": len(reject_events),
            "avg_candidate_score": avg_score,
            "max_candidate_score": max_score,
            "min_candidate_score": min_score,
            "status": "BACKTEST_EVALUATION_READY",
        }
