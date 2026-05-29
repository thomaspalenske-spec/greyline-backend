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

    def get_all_trades(self):
        return self.load()["trades"]

    def add_trade(self, trade):
        data = self.load()
        data["trades"].append(trade)
        self.save(data)

    def trade_count(self):
        return len(self.get_all_trades())
