class SnapshotLedgerReconciliationEngine:

    def _active_ledger_symbols(self, ledger_trades):
        return {
            trade.get("symbol")
            for trade in ledger_trades
            if trade.get("state") == "ACTIVE" and trade.get("symbol")
        }

    def _snapshot_symbols(self, snapshot_positions):
        return {
            position.get("symbol")
            for position in snapshot_positions
            if position.get("symbol")
        }

    def reconcile(self, ledger, snapshot):
        ledger_trades = ledger.get("trades", [])
        snapshot_positions = snapshot.get("positions", [])

        ledger_symbols = self._active_ledger_symbols(ledger_trades)
        snapshot_symbols = self._snapshot_symbols(snapshot_positions)

        missing_from_snapshot = sorted(list(ledger_symbols - snapshot_symbols))
        unexpected_in_snapshot = sorted(list(snapshot_symbols - ledger_symbols))

        reconciled = (
            len(missing_from_snapshot) == 0
            and len(unexpected_in_snapshot) == 0
        )

        return {
            "ledger_active_count": len(ledger_symbols),
            "snapshot_position_count": len(snapshot_symbols),
            "missing_from_snapshot": missing_from_snapshot,
            "unexpected_in_snapshot": unexpected_in_snapshot,
            "reconciled": reconciled,
            "execution_lockout_required": not reconciled,
            "status": "SNAPSHOT_LEDGER_RECONCILED" if reconciled else "SNAPSHOT_LEDGER_MISMATCH"
        }
