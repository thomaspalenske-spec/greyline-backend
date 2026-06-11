from datetime import datetime


class GreyLineLedgerFeedbackLoopEngine:

    def apply(self, executed_result, ledger_writer):

        executed_trades = executed_result.get("executed_trades", [])

        ledger_entries = []

        for trade in executed_trades:

            ledger_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": trade.get("symbol"),
                "event_type": "TRADE_EXECUTED",
                "fill_price": trade.get("fill_price"),
                "quantity": trade.get("quantity"),
                "allocation": trade.get("allocation"),
                "slippage_bps": trade.get("slippage_bps")
            }

            ledger_entries.append(ledger_entry)

        ledger_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "trade_count": len(ledger_entries),
            "ledger_entries": ledger_entries,
            "status": "LEDGER_FEEDBACK_APPLIED"
        }

        # Persist via writer if provided
        if ledger_writer:
            ledger_writer.write({
                "positions": [],
                "total_unrealized_pnl": 0
            })

        return ledger_record
