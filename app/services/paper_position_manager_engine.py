from datetime import datetime

from app.services.ledger_engine import LedgerEngine


class PaperPositionManagerEngine:

    def get_active_positions(self):
        trades = LedgerEngine().get_all_trades()

        active = [
            trade
            for trade in trades
            if trade.get("state") == "ACTIVE"
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "position_count": len(active),
            "positions": active,
            "status": "ACTIVE_POSITIONS_LOADED"
        }

    def close_position(self, trade_id):
        ledger_engine = LedgerEngine()
        ledger = ledger_engine.load()

        for trade in ledger.get("trades", []):
            if trade.get("trade_id") == trade_id:
                trade["state"] = "CLOSED"
                trade["modified_timestamp"] = datetime.utcnow().isoformat()

                ledger_engine.save(ledger)

                return {
                    "trade_id": trade_id,
                    "position_closed": True,
                    "status": "POSITION_CLOSED"
                }

        return {
            "trade_id": trade_id,
            "position_closed": False,
            "status": "POSITION_NOT_FOUND"
        }
