import json
from datetime import datetime
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class OptionsPositionManagerEngine:

    def __init__(self):
        self.ledger_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")

    def manage_open_positions(self):
        if not self.ledger_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "positions_checked": 0,
                "positions_closed": 0,
                "status": "NO_OPTIONS_PAPER_LEDGER",
            }

        trades = [
            json.loads(line)
            for line in self.ledger_file.read_text().splitlines()
            if line.strip()
        ]

        updated = []
        checked = 0
        closed = []

        for trade in trades:
            if trade.get("status") != "OPEN":
                updated.append(trade)
                continue

            checked += 1
            option_symbol = trade.get("option_symbol")
            entry_price = float(trade.get("entry_price") or 0)
            contracts = int(trade.get("contracts") or 0)

            quote = TradeStationQuoteLiveEngine().get_quote(option_symbol)
            quote_row = ((quote.get("response_json") or {}).get("Quotes") or [{}])[0]

            current_price = float(
                quote_row.get("Last")
                or quote_row.get("Mid")
                or quote_row.get("Bid")
                or 0
            )

            if current_price <= 0 or entry_price <= 0:
                trade["manager_status"] = "OPTION_PRICE_UNAVAILABLE"
                trade["last_managed_at"] = datetime.utcnow().isoformat()
                updated.append(trade)
                continue

            pnl = round((current_price - entry_price) * contracts * 100, 2)
            pnl_pct = round(((current_price / entry_price) - 1) * 100, 2)

            trade["current_price"] = current_price
            trade["unrealized_pnl"] = pnl
            trade["unrealized_pnl_pct"] = pnl_pct
            trade["last_managed_at"] = datetime.utcnow().isoformat()
            trade["manager_status"] = "OPTION_POSITION_UPDATED"

            if pnl_pct >= 50:
                trade["status"] = "CLOSED"
                trade["exit_price"] = current_price
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["realized_pnl"] = pnl
                trade["realized_pnl_pct"] = pnl_pct
                trade["exit_reason"] = "OPTIONS_TAKE_PROFIT_50_PCT"
                closed.append(trade)

            elif pnl_pct <= -35:
                trade["status"] = "CLOSED"
                trade["exit_price"] = current_price
                trade["exit_timestamp"] = datetime.utcnow().isoformat()
                trade["realized_pnl"] = pnl
                trade["realized_pnl_pct"] = pnl_pct
                trade["exit_reason"] = "OPTIONS_STOP_LOSS_35_PCT"
                closed.append(trade)

            updated.append(trade)

        self.ledger_file.write_text(
            "\n".join(json.dumps(t) for t in updated) + ("\n" if updated else "")
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_POSITION_MANAGER",
            "positions_checked": checked,
            "positions_closed": len(closed),
            "closed_positions": closed,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_POSITION_MANAGER_COMPLETE",
        }
