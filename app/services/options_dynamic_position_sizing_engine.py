class OptionsDynamicPositionSizingEngine:
    def max_position_pct(self, score, reliability_score=None):
        try:
            score = float(score or 0)
        except Exception:
            score = 0.0

        try:
            reliability_score = float(reliability_score if reliability_score is not None else score)
        except Exception:
            reliability_score = score

        if score >= 90:
            base = 0.15
        elif score >= 85:
            base = 0.10
        elif score >= 80:
            base = 0.075
        else:
            base = 0.05

        if reliability_score >= 90:
            multiplier = 1.00
        elif reliability_score >= 80:
            multiplier = 0.85
        elif reliability_score >= 70:
            multiplier = 0.65
        elif reliability_score >= 60:
            multiplier = 0.40
        else:
            multiplier = 0.25

        return round(base * multiplier, 4)
