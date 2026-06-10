import json
from pathlib import Path
from datetime import datetime


class LedgerEngine:
    def __init__(self):
        self.ledger_path = Path("app/data/trade_ledger.json")

        if not self.ledger_path.exists():
            self.ledger_path.write_text(
                json.dumps(
                    {
                        "created": datetime.utcnow().isoformat(),
                        "trades": []
                    },
                    indent=4
                )
            )

    def load(self):
        with open(self.ledger_path, "r") as f:
            return json.load(f)

    def save(self, data):
        with open(self.ledger_path, "w") as f:
            json.dump(data, f, indent=4)

    def _existing_trade_ids(self, ledger):
        return {
            trade.get("trade_id")
            for trade in ledger.get("trades", [])
            if trade.get("trade_id")
        }

    def add_trade(self, trade):
        ledger = self.load()

        trade_id = trade.get("trade_id")

        if not trade_id:
            return {
                "status": "trade_rejected",
                "reason": "missing_trade_id",
                "trade_saved": False,
                "trade_count": len(ledger.get("trades", []))
            }

        if trade_id in self._existing_trade_ids(ledger):
            return {
                "status": "trade_rejected",
                "reason": "duplicate_trade_id",
                "trade_id": trade_id,
                "trade_saved": False,
                "trade_count": len(ledger.get("trades", []))
            }

        trade["created_at"] = datetime.utcnow().isoformat()

        ledger["trades"].append(trade)

        self.save(ledger)

        return {
            "status": "trade_saved",
            "trade_id": trade_id,
            "trade_saved": True,
            "trade_count": len(ledger["trades"])
        }

    def get_all_trades(self):
        return self.load()["trades"]

    def trade_count(self):
        return len(self.get_all_trades())
