import json
from datetime import datetime
from pathlib import Path
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class PaperTradeLedgerEngine:
    def __init__(self):
        self.ledger_dir = Path("app/data/paper_trading")
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.ledger_dir / "paper_trade_ledger.jsonl"

    def open_trade(self, symbol="PLTR", side="BUY", quantity=1, entry_price=0.0):
        trade = {
            "trade_id": f"{symbol}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeLedgerEngine",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "entry_price": float(entry_price),
            "exit_price": None,
            "realized_pnl": 0.0,
            "status": "OPEN",
            "execution_mode": "PAPER_ONLY",
            "live_order_placement_attempted": False,
        }

        with self.ledger_file.open("a") as f:
            f.write(json.dumps(trade) + "\n")

        audit = ImmutableAuditLedgerEngine().record("PAPER_TRADE_LEDGER_OPENED", trade)

        trade["audit_logged"] = True
        trade["audit_result"] = audit
        return trade

    def close_latest(self, symbol="PLTR", exit_price=0.0):
        trades = self._read_all()
        open_trades = [t for t in trades if t.get("symbol") == symbol and t.get("status") == "OPEN"]

        if not open_trades:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "closed": False,
                "reason": "No open paper trade found.",
                "status": "NO_OPEN_PAPER_TRADE",
            }

        trade = open_trades[-1]
        trade["exit_price"] = float(exit_price)

        if trade.get("side") == "BUY":
            trade["realized_pnl"] = round((trade["exit_price"] - trade["entry_price"]) * trade["quantity"], 2)
        else:
            trade["realized_pnl"] = round((trade["entry_price"] - trade["exit_price"]) * trade["quantity"], 2)

        trade["closed_timestamp"] = datetime.utcnow().isoformat()
        trade["status"] = "CLOSED"

        remaining = []
        replaced = False
        for t in trades:
            if t.get("trade_id") == trade.get("trade_id") and not replaced:
                remaining.append(trade)
                replaced = True
            else:
                remaining.append(t)

        with self.ledger_file.open("w") as f:
            for t in remaining:
                f.write(json.dumps(t) + "\n")

        audit = ImmutableAuditLedgerEngine().record("PAPER_TRADE_LEDGER_CLOSED", trade)

        trade["audit_logged"] = True
        trade["audit_result"] = audit
        return trade

    def history(self):
        trades = self._read_all()
        open_count = len([t for t in trades if t.get("status") == "OPEN"])
        closed = [t for t in trades if t.get("status") == "CLOSED"]
        total_realized_pnl = round(sum(t.get("realized_pnl", 0.0) for t in closed), 2)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeLedgerEngine",
            "trade_count": len(trades),
            "open_trade_count": open_count,
            "closed_trade_count": len(closed),
            "total_realized_pnl": total_realized_pnl,
            "trades": trades,
            "status": "PAPER_TRADE_LEDGER_READY",
        }

    def _read_all(self):
        if not self.ledger_file.exists():
            return []

        trades = []
        with self.ledger_file.open("r") as f:
            for line in f:
                try:
                    trades.append(json.loads(line))
                except Exception:
                    continue
        return trades
