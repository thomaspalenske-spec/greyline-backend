class PortfolioEngine:

    def __init__(self):
        self.active_positions = [
            "NVDA",
            "AVGO",
            "MSFT"
        ]

        self.watch_positions = [
            "AMD",
            "PLTR",
            "TSM"
        ]

    def get_portfolio_state(self):

        return {
            "execute": self.active_positions,
            "watch": self.watch_positions,
            "portfolio_bias": "SELECTIVE_AGGRESSION",
            "cash_state": "MODERATE_DEPLOYMENT"
        }


