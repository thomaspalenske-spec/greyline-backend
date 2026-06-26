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

        def _result(e):
            existing = str(e.get("result", "")).upper()
            if existing:
                return existing

            score = float(e.get("score") or e.get("composite_score") or e.get("adjusted_score") or 0)
            liquidity = float(e.get("liquidity_score") or 0)

            if score >= 85 and liquidity >= 70:
                return "EXECUTE"
            if score >= 70:
                return "WATCH"
            return "REJECT"

        execute_events = [e for e in candidate_events if _result(e) == "EXECUTE"]
        watch_events = [e for e in candidate_events if _result(e) == "WATCH"]
        reject_events = [e for e in candidate_events if _result(e) == "REJECT"]

        scores = [
            float(e.get("score") or e.get("composite_score") or e.get("adjusted_score") or 0)
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
