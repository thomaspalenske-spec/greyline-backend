import json
from datetime import datetime
from pathlib import Path


class OptionsAccountDashboardEngine:

    def __init__(self):
        self.starting_equity = 10000.0
        self.ledger_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")

    def get_dashboard(self):
        trades = []

        if self.ledger_file.exists():
            trades = [
                json.loads(line)
                for line in self.ledger_file.read_text().splitlines()
                if line.strip()
            ]

        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]

        realized_pnl = round(sum(float(t.get("realized_pnl") or 0) for t in closed_trades), 2)
        unrealized_pnl = round(sum(float(t.get("unrealized_pnl") or 0) for t in open_trades), 2)

        current_equity = round(self.starting_equity + realized_pnl + unrealized_pnl, 2)

        wins = [t for t in closed_trades if float(t.get("realized_pnl") or 0) > 0]
        losses = [t for t in closed_trades if float(t.get("realized_pnl") or 0) < 0]

        win_rate_pct = round((len(wins) / len(closed_trades)) * 100, 2) if closed_trades else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "account_type": "OPTIONS_PAPER_TRADING",
            "starting_equity": self.starting_equity,
            "current_equity": current_equity,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_return_pct": round(((current_equity - self.starting_equity) / self.starting_equity) * 100, 2),
            "option_trade_count": len(trades),
            "open_option_trade_count": len(open_trades),
            "closed_option_trade_count": len(closed_trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": win_rate_pct,
            "open_positions": open_trades,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_ACCOUNT_DASHBOARD_READY",
        }
