from datetime import datetime


class SignalDecayEngine:
    def evaluate(self, age_days=0):
        age_days = max(0, float(age_days))

        decay = max(0, 100 - (age_days * 10))

        if decay >= 80:
            strength = "FRESH"
        elif decay >= 50:
            strength = "AGING"
        else:
            strength = "STALE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "SignalDecayEngine",
            "signal_age_days": age_days,
            "signal_strength_score": round(decay, 2),
            "signal_state": strength,
            "status": "SIGNAL_DECAY_READY",
        }
