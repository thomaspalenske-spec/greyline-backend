class HistoricalExitPolicyOptimizer:
    """
    Simulator only.

    Chooses the best historical exit policy for a trade environment.

    Production engines are NOT modified.
    The simulator adapts to GreyLine.
    """

    def choose(
        self,
        regime_score,
        risk_state_score,
        direction_confidence,
        volatility_score,
    ):
        regime_score = float(regime_score or 0)
        risk_state_score = float(risk_state_score or 0)
        direction_confidence = float(direction_confidence or 0)
        volatility_score = float(volatility_score or 0)

        # Weak or unstable conditions: harvest simply and avoid long runner exposure.
        if risk_state_score < 65:
            return "SINGLE_EXIT"

        # Very strong environment: let divestment be adaptive and keep more runner.
        if (
            regime_score >= 88
            and risk_state_score >= 72
            and direction_confidence >= 30
        ):
            return "DYNAMIC_DIVESTMENT"

        # High volatility with decent risk control: keep runner optional.
        if volatility_score >= 75 and risk_state_score >= 70:
            return "RUNNER"

        # Default remains staged TP, but this should now be less dominant.
        return "STANDARD_DYNAMIC_TP"
