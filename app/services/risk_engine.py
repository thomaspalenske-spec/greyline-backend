class RiskEngine:

    def __init__(self):
        self.drawdown_state = "NORMAL"
        self.correlation_state = "CONTROLLED"
        self.liquidity_state = "STABLE"

    def evaluate_risk_state(self):

        if self.drawdown_state == "HALTED":
            return "HALTED"

        if self.correlation_state == "EXTREME":
            return "DEFENSIVE"

        if self.liquidity_state == "STRESSED":
            return "DEFENSIVE"

        return "NORMAL"
