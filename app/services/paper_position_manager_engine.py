import json
from datetime import datetime
from pathlib import Path

from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class PaperPositionManagerEngine:

    def __init__(self):
        self.ledger_file = Path("app/data/paper_trading/paper_trade_ledger.jsonl")

    def manage_open_positions(self):
        ledger = PaperTradeLedgerEngine().history(limit=10000)
        trades = ledger.get("trades", [])

        if not trades:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "positions_checked": 0,
                "positions_closed": 0,
                "status": "PAPER_POSITION_MANAGER_NO_TRADES",
            }

        updated = []
        closed = []

        for trade in trades:
            if trade.get("status") != "OPEN":
                updated.append(trade)
                continue

            symbol = trade.get("symbol")
            entry_price = float(trade.get("entry_price") or 0)
            quantity = float(trade.get("quantity") or 0)

            quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
            quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
            quote_row = quotes[0] if quotes else {}

            try:
                current_price = float(quote_row.get("Last") or 0)
            except Exception:
                current_price = 0.0

            if entry_price <= 0 or current_price <= 0:
                trade["manager_status"] = "PRICE_UNAVAILABLE"
                updated.append(trade)
                continue

            pnl = (current_price - entry_price) * quantity
            pnl_pct = ((current_price / entry_price) - 1) * 100

            should_close = pnl_pct >= 10 or pnl_pct <= -5

            trade["current_price"] = current_price
            trade["unrealized_pnl"] = round(pnl, 2)
            trade["unrealized_pnl_pct"] = round(pnl_pct, 2)
            trade["last_managed_at"] = datetime.utcnow().isoformat()

            if should_close:
                trade["status"] = "CLOSED"
                trade["exit_price"] = current_price
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["realized_pnl"] = round(pnl, 2)
                trade["realized_pnl_pct"] = round(pnl_pct, 2)
                trade["exit_reason"] = "TAKE_PROFIT" if pnl_pct >= 10 else "STOP_LOSS"
                closed.append(trade)

            updated.append(trade)

        self.ledger_file.write_text(
            "\n".join(json.dumps(t) for t in updated) + ("\n" if updated else "")
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "positions_checked": len([t for t in trades if t.get("status") == "OPEN"]),
            "positions_closed": len(closed),
            "closed_positions": closed,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "PAPER_POSITION_MANAGER_COMPLETE",
        }
