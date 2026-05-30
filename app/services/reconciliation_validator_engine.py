class ReconciliationValidatorEngine:

    def validate(self, ledger_positions, active_positions):

        report = {
            "ledger_count": len(ledger_positions),
            "active_count": len(active_positions),
            "difference": len(ledger_positions) - len(active_positions),
            "status": "PASS"
        }

        if report["difference"] != 0:
            report["status"] = "FAIL"

        return report
