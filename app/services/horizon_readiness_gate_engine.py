from datetime import datetime


class HorizonReadinessGateEngine:
    def evaluate(self, horizon_tracker):
        eligible = horizon_tracker.get("eligible_counts") or {}

        eligible_1h = int(eligible.get("eligible_1h") or 0)
        eligible_4h = int(eligible.get("eligible_4h") or 0)
        eligible_1d = int(eligible.get("eligible_1d") or 0)
        eligible_3d = int(eligible.get("eligible_3d") or 0)
        eligible_10d = int(eligible.get("eligible_10d") or 0)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HorizonReadinessGateEngine",
            "horizon_return_tracking_state": {
                "one_hour": "READY" if eligible_1h >= 25 else "WAIT_FOR_MORE_SAMPLES",
                "four_hour": "READY" if eligible_4h >= 25 else "WAIT_FOR_MORE_SAMPLES",
                "one_day": "READY" if eligible_1d >= 25 else "WAIT_FOR_MORE_SAMPLES",
                "three_day": "READY" if eligible_3d >= 25 else "WAIT_FOR_MORE_SAMPLES",
                "ten_day": "READY" if eligible_10d >= 25 else "WAIT_FOR_MORE_SAMPLES",
            },
            "eligible_counts": eligible,
            "minimum_samples_per_horizon": 25,
            "status": "HORIZON_READINESS_GATE_READY",
        }
