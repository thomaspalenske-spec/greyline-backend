from datetime import datetime


class BattlefieldTrendEngine:

    def _num(self, value, default=0.0):
        try:
            return float(value)
        except Exception:
            return default

    def evaluate(self, history):
        valid = [r for r in history if r.get("battlefield_health") not in [None, "UNKNOWN"]]

        if len(valid) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "trend": "INSUFFICIENT_HISTORY",
                "trend_strength": 0,
                "hours_in_state": 0,
                "best_call_score_change": 0,
                "best_put_score_change": 0,
                "ready_call_count_change": 0,
                "ready_put_count_change": 0,
                "status": "BATTLEFIELD_TREND_READY",
            }

        first = valid[0]
        last = valid[-1]

        call_change = self._num(last.get("best_call_score")) - self._num(first.get("best_call_score"))
        put_change = self._num(last.get("best_put_score")) - self._num(first.get("best_put_score"))
        ready_call_change = self._num(last.get("ready_call_count")) - self._num(first.get("ready_call_count"))
        ready_put_change = self._num(last.get("ready_put_count")) - self._num(first.get("ready_put_count"))

        trend_points = 0
        trend_points += call_change * 5
        trend_points += ready_call_change * 15
        trend_points -= put_change * 2
        trend_points -= ready_put_change * 10

        if trend_points >= 15:
            trend = "IMPROVING"
        elif trend_points <= -15:
            trend = "DETERIORATING"
        else:
            trend = "STABLE"

        trend_strength = min(100, round(abs(trend_points), 2))

        current_state = last.get("battlefield_health")
        state_rows = [r for r in reversed(valid) if r.get("battlefield_health") == current_state]
        hours_in_state = 0

        try:
            oldest_same = state_rows[-1]
            start = datetime.fromisoformat(str(oldest_same.get("timestamp")).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(last.get("timestamp")).replace("Z", "+00:00"))
            hours_in_state = round((end - start).total_seconds() / 3600, 2)
        except Exception:
            hours_in_state = 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "trend": trend,
            "trend_strength": trend_strength,
            "hours_in_state": hours_in_state,
            "current_state": current_state,
            "best_call_score_change": round(call_change, 2),
            "best_put_score_change": round(put_change, 2),
            "ready_call_count_change": int(ready_call_change),
            "ready_put_count_change": int(ready_put_change),
            "sample_count": len(valid),
            "status": "BATTLEFIELD_TREND_READY",
        }
