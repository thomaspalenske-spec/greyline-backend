class AccountDriftDetectorEngine:

    DEFAULT_TOLERANCE = 0.01

    def detect_drift(
        self,
        ledger_equity,
        reported_equity,
        tolerance=None
    ):

        tolerance = self.DEFAULT_TOLERANCE if tolerance is None else tolerance

        if ledger_equity is None or reported_equity is None:
            return {
                "ledger_equity": ledger_equity,
                "reported_equity": reported_equity,
                "difference": None,
                "absolute_difference": None,
                "tolerance": tolerance,
                "drift_detected": None,
                "severity": "UNKNOWN",
                "execution_lockout_required": True,
                "status": "ACCOUNT_DRIFT_UNKNOWN"
            }

        difference = reported_equity - ledger_equity
        absolute_difference = abs(difference)
        drift_detected = absolute_difference > tolerance

        if not drift_detected:
            severity = "CLEAR"
        elif absolute_difference <= 100:
            severity = "LOW"
        elif absolute_difference <= 1000:
            severity = "MEDIUM"
        else:
            severity = "HIGH"

        return {
            "ledger_equity": ledger_equity,
            "reported_equity": reported_equity,
            "difference": difference,
            "absolute_difference": absolute_difference,
            "tolerance": tolerance,
            "drift_detected": drift_detected,
            "severity": severity,
            "execution_lockout_required": drift_detected,
            "status": "ACCOUNT_DRIFT_DETECTED" if drift_detected else "ACCOUNT_DRIFT_CLEAR"
        }
