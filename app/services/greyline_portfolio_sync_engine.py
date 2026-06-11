from datetime import datetime


class GreyLinePortfolioSyncEngine:

    def sync(self, broker_positions, ledger_positions):

        broker_map = {p["symbol"]: p for p in broker_positions}
        ledger_map = {p["symbol"]: p for p in ledger_positions}

        synced = []
        mismatches = []

        all_symbols = set(broker_map.keys()) | set(ledger_map.keys())

        for symbol in all_symbols:

            broker_pos = broker_map.get(symbol)
            ledger_pos = ledger_map.get(symbol)

            if not broker_pos or not ledger_pos:
                mismatches.append({
                    "symbol": symbol,
                    "reason": "MISSING_IN_ONE_SOURCE",
                    "broker": broker_pos,
                    "ledger": ledger_pos
                })
                continue

            drift = abs(
                broker_pos.get("quantity", 0)
                - ledger_pos.get("quantity", 0)
            )

            synced.append({
                "symbol": symbol,
                "broker_qty": broker_pos.get("quantity"),
                "ledger_qty": ledger_pos.get("quantity"),
                "drift": drift,
                "in_sync": drift == 0
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "synced_positions": synced,
            "mismatches": mismatches,
            "sync_status": "IN_SYNC" if len(mismatches) == 0 else "DRIFT_DETECTED"
        }
