class AccountDriftDetectorEngine:

    def detect_drift(
        self,
        ledger_equity,
        reported_equity
    ):

        difference = reported_equity - ledger_equity

        return {
            "ledger_equity": ledger_equity,
            "reported_equity": reported_equity,
            "difference": difference,
            "drift_detected": difference != 0
        }
