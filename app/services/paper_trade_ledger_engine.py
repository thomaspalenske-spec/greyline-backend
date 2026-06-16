import json
from datetime import datetime
from pathlib import Path


class PaperTradeLedgerEngine:

    def __init__(self):
        self.data_dir = Path("app/data/paper_trading")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / "paper_trade_ledger.jsonl"

    def record_trade(
        self,
        symbol,
        side,
        quantity,
        entry_price,
        source="GREYLINE_MASTER_DECISION",
    ):
        trade = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "source": source,
            "status": "OPEN",
        }

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(trade) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "PAPER_TRADE_LEDGER",
            "trade_recorded": True,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "status": "PAPER_TRADE_RECORDED",
        }

    def history(self, limit=100):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "source": "PAPER_TRADE_LEDGER",
                "trade_count": 0,
                "trades": [],
                "status": "NO_PAPER_TRADES",
            }

        lines = self.ledger_file.read_text().splitlines()
        trades = [json.loads(line) for line in lines[-limit:]]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "PAPER_TRADE_LEDGER",
            "trade_count": len(trades),
            "trades": trades,
            "status": "PAPER_TRADE_HISTORY_READY",
        }
