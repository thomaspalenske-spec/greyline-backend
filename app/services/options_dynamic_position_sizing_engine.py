class OptionsDynamicPositionSizingEngine:
    def max_position_pct(self, score):
        try:
            score = float(score or 0)
        except Exception:
            score = 0.0

        if score >= 90:
            return 0.15
        if score >= 85:
            return 0.10
        if score >= 80:
            return 0.075
        return 0.05
