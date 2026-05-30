from datetime import datetime


class ReconciliationReportEngine:

    def generate_report(self, ledger_positions, active_positions):

        ledger_symbols = [position.get("symbol") for position in ledger_positions]
        active_symbols = [position.get("symbol") for position in active_positions]

        missing_positions = [
            symbol for symbol in ledger_symbols
            if symbol not in active_symbols
        ]

        unexpected_positions = [
            symbol for symbol in active_symbols
            if symbol not in ledger_symbols
        ]

        status = "PASS"

        if missing_positions or unexpected_positions:
            status = "FAIL"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "ledger_count": len(ledger_positions),
            "active_count": len(active_positions),
            "missing_positions": missing_positions,
            "unexpected_positions": unexpected_positions,
            "difference_count": len(missing_positions) + len(unexpected_positions),
            "status": status
        }
