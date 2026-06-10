from datetime import datetime

from app.services.ledger_engine import LedgerEngine


class LedgerQuarantineReportEngine:

    def generate(self):

        ledger = LedgerEngine().load()

        trades = ledger.get("trades", [])

        quarantined = []

        for index, trade in enumerate(trades):

            reasons = []

            if not trade.get("trade_id"):
                reasons.append("MISSING_TRADE_ID")

            if not trade.get("symbol"):
                reasons.append("MISSING_SYMBOL")

            if not trade.get("state"):
                reasons.append("MISSING_STATE")

            if reasons:
                quarantined.append(
                    {
                        "index": index,
                        "trade": trade,
                        "reasons": reasons
                    }
                )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "trade_count": len(trades),
            "quarantined_count": len(quarantined),
            "quarantined": quarantined,
            "status": (
                "LEDGER_CLEAN"
                if len(quarantined) == 0
                else "LEDGER_QUARANTINE_REQUIRED"
            )
        }
