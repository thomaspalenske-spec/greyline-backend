class HistoricalExitPolicyOptimizer:
    """
    Simulator only.

    Determines which exit policy historically performed best for
    a particular market environment.

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
        if (
            regime_score >= 90
            and risk_state_score >= 80
            and direction_confidence >= 35
        ):
            return "DYNAMIC_DIVESTMENT"

        if volatility_score >= 80:
            return "RUNNER"

        if risk_state_score < 65:
            return "SINGLE_EXIT"

        return "STANDARD_DYNAMIC_TP"
