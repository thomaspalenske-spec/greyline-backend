from pathlib import Path
from datetime import datetime

from app.services.persistence.json_store import atomic_write_json, read_json


def _normalize_ledger(data):
    if not isinstance(data, dict):
        return {"created": datetime.utcnow().isoformat(), "trades": []}
    data.setdefault("trades", [])
    return data


class LedgerEngine:
    def __init__(self):
        self.ledger_path = Path("app/data/trade_ledger.json")

    def load(self):
        # Self-healing: missing/empty/corrupt -> fresh ledger, never crashes.
        return read_json(
            self.ledger_path,
            default=lambda: {"created": datetime.utcnow().isoformat(), "trades": []},
            normalizer=_normalize_ledger,
        )

    def save(self, data):
        # Atomic + durable: a crash mid-write can never truncate the trade ledger.
        atomic_write_json(self.ledger_path, data, indent=4)

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
