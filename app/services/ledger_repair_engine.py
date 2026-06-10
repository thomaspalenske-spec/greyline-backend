from datetime import datetime

from app.services.ledger_engine import LedgerEngine


class LedgerRepairEngine:

    def repair(
        self,
        approved_candidates
    ):

        ledger_engine = LedgerEngine()

        ledger = ledger_engine.load()

        trades = ledger.get("trades", [])

        repairs_applied = 0

        for candidate in approved_candidates:

            index = candidate.get("index")
            proposed_trade_id = candidate.get(
                "proposed_trade_id"
            )

            if (
                index is not None
                and index < len(trades)
                and not trades[index].get("trade_id")
            ):

                trades[index]["trade_id"] = (
                    proposed_trade_id
                )

                repairs_applied += 1

        ledger_engine.save(ledger)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "repairs_applied": repairs_applied,
            "status": "LEDGER_REPAIR_COMPLETE"
        }
