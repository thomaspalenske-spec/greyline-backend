import json
from pathlib import Path
from app.services.reconciliation_engine import ReconciliationEngine

class AccountEngine:
    def __init__(self):
        self.initial_balance = 10000.00
        self.ledger_path = Path("app/data/trade_ledger.json")

    def load_ledger(self):
        if not self.ledger_path.exists():
            return {"trades": []}

        with open(self.ledger_path, "r") as f:
            return json.load(f)

    def get_account_status(self):
        ledger = self.load_ledger()
        trades = ledger.get("trades", [])

        realized_pnl = sum(
            trade.get("realized_pnl", 0.0)
            for trade in trades
        )

        open_positions = [
            trade for trade in trades
            if trade.get("state") == "ACTIVE"
        ]

        cash_balance = self.initial_balance + realized_pnl

        return {
            "account_name": "GreyLine Account 3",
            "state": "SIMULATED",
            "campaign_origin": "ACTIVE_OPERATIONAL_SIMULATION",
            "initial_balance": self.initial_balance,
            "cash_balance": cash_balance,
            "realized_pnl": realized_pnl,
            "open_positions_count": len(open_positions)
            ,"closed_positions_count": len([
    trade for trade in trades
    if trade.get("state") == "CLOSED"
]),
            "total_trades": len(trades),
            "confidence": "LEDGER_BASED_SIMULATION"
        }