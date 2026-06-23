from datetime import datetime


class BattlefieldMomentumEngine:

    def evaluate(self, history):

        valid = [
            x for x in history
            if x.get("best_call_score") is not None
        ]

        if len(valid) < 2:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "momentum_state": "INSUFFICIENT_HISTORY",
                "momentum_strength": 0,
                "status": "BATTLEFIELD_MOMENTUM_READY",
            }

        latest = valid[-1]
        prior = valid[-2]

        call_change = (
            float(latest.get("best_call_score") or 0)
            - float(prior.get("best_call_score") or 0)
        )

        put_change = (
            float(latest.get("best_put_score") or 0)
            - float(prior.get("best_put_score") or 0)
        )

        ready_call_change = (
            int(latest.get("ready_call_count") or 0)
            - int(prior.get("ready_call_count") or 0)
        )

        ready_put_change = (
            int(latest.get("ready_put_count") or 0)
            - int(prior.get("ready_put_count") or 0)
        )

        strength = round(call_change + ready_call_change * 5, 2)

        state = "STABLE"

        if strength > 1:
            state = "IMPROVING"

        if strength < -1:
            state = "DETERIORATING"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "momentum_state": state,
            "momentum_strength": strength,
            "best_call_score_change": round(call_change, 2),
            "best_put_score_change": round(put_change, 2),
            "ready_call_count_change": ready_call_change,
            "ready_put_count_change": ready_put_change,
            "status": "BATTLEFIELD_MOMENTUM_READY",
        }
