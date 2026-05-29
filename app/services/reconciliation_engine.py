from app.services.ledger_engine import LedgerEngine


class ReconciliationEngine:

    def __init__(self):
        self.ledger = LedgerEngine()

    def reconcile(self):

        data = self.ledger.load()

        trades = data.get("trades", [])

        active_positions = []
        closed_positions = []

        for trade in trades:

            if trade.get("state") == "ACTIVE":
                active_positions.append(trade)

            if trade.get("state") == "CLOSED":
                closed_positions.append(trade)

        return {
            "active_positions": active_positions,
            "closed_positions": closed_positions,
            "active_count": len(active_positions),
            "closed_count": len(closed_positions)
        }