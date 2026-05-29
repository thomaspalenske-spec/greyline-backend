class AccountEngine:

    def __init__(self):
        self.initial_balance = 10000.00

    def get_account_status(self):
        return {
            "balance": self.initial_balance,
            "state": "SIMULATED",
            "confidence": "LEDGER_BASED"
        }
