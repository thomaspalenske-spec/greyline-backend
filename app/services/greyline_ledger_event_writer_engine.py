from datetime import datetime


class GreyLineLedgerEventWriterEngine:

    def write(self, processed_result):

        positions = processed_result.get("positions", [])
        pnl = processed_result.get("total_unrealized_pnl", 0)

        ledger_events = []

        for pos in positions:

            ledger_events.append({
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": pos.get("symbol"),
                "event_type": "POSITION_MARK_TO_MARKET",
                "entry_price": pos.get("entry_price"),
                "current_price": pos.get("current_price"),
                "quantity": pos.get("quantity"),
                "unrealized_pnl": pos.get("unrealized_pnl"),
            })

        ledger_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_count": len(ledger_events),
            "total_unrealized_pnl": pnl,
            "ledger_events": ledger_events,
            "status": "LEDGER_EVENT_WRITE_COMPLETE"
        }

        return ledger_record
