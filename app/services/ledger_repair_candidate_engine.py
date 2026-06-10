from datetime import datetime

from app.services.ledger_quarantine_report_engine import (
    LedgerQuarantineReportEngine
)


class LedgerRepairCandidateEngine:

    def generate_candidates(self):
        report = LedgerQuarantineReportEngine().generate()

        candidates = []

        for item in report.get("quarantined", []):
            trade = item.get("trade", {})
            reasons = item.get("reasons", [])

            if "MISSING_TRADE_ID" in reasons:
                symbol = trade.get("symbol", "UNKNOWN")
                index = item.get("index")

                candidates.append(
                    {
                        "index": index,
                        "symbol": symbol,
                        "repair_type": "ASSIGN_RECONSTRUCTED_TRADE_ID",
                        "proposed_trade_id": f"GL-REPAIRED-{index:04d}",
                        "requires_manual_approval": True,
                        "original_trade": trade,
                        "status": "REPAIR_CANDIDATE_READY"
                    }
                )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source_status": report.get("status"),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "status": (
                "LEDGER_REPAIR_CANDIDATES_READY"
                if candidates
                else "NO_LEDGER_REPAIR_CANDIDATES"
            )
        }
