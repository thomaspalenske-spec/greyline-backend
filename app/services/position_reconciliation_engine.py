from app.services.ledger_engine import LedgerEngine


class PositionReconciliationEngine:

    VALID_STATES = {
        "ACTIVE",
        "CLOSED"
    }

    def reconcile_positions(self):
        ledger = LedgerEngine().load()

        active_positions = []
        closed_positions = []
        invalid_trades = []

        trades = ledger.get("trades", [])

        for trade in trades:

            trade_id = trade.get("trade_id")
            state = trade.get("state")

            if not trade_id:
                invalid_trades.append(
                    {
                        "reason": "missing_trade_id",
                        "trade": trade
                    }
                )

            if state not in self.VALID_STATES:
                invalid_trades.append(
                    {
                        "reason": "invalid_state",
                        "trade": trade
                    }
                )

            if state == "ACTIVE":
                active_positions.append(trade)

            if state == "CLOSED":
                closed_positions.append(trade)

        reconciled = (
            len(active_positions)
            + len(closed_positions)
            == len(trades)
        )

        if invalid_trades:
            reconciliation_status = "FAIL"
        elif reconciled:
            reconciliation_status = "PASS"
        else:
            reconciliation_status = "WARNING"

        return {
            "active_positions": active_positions,
            "closed_positions": closed_positions,
            "active_count": len(active_positions),
            "closed_count": len(closed_positions),
            "ledger_total": len(trades),
            "invalid_trade_count": len(invalid_trades),
            "invalid_trades": invalid_trades,
            "reconciled": reconciled,
            "reconciliation_status": reconciliation_status
        }
