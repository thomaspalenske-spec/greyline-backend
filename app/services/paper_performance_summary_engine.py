from datetime import datetime

from app.services.paper_drawdown_engine import PaperDrawdownEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


class PaperPerformanceSummaryEngine:

    def summarize(self):
        starting_equity = 10000.0

        ledger = PaperTradeLedgerEngine().history(limit=10000)
        trades = ledger.get("trades", [])

        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]
        symbols = sorted(list(set(t.get("symbol") for t in trades if t.get("symbol"))))

        realized_pnl = round(sum(float(t.get("realized_pnl") or 0) for t in closed_trades), 2)
        unrealized_pnl = round(sum(float(t.get("unrealized_pnl") or 0) for t in open_trades), 2)

        latest_equity = round(starting_equity + realized_pnl + unrealized_pnl, 2)
        highest_equity = max(starting_equity, latest_equity)

        total_return_pct = round(((latest_equity - starting_equity) / starting_equity) * 100, 2)

        wins = [t for t in closed_trades if float(t.get("realized_pnl") or 0) > 0]
        losses = [t for t in closed_trades if float(t.get("realized_pnl") or 0) < 0]

        win_rate_pct = 0
        if closed_trades:
            win_rate_pct = round((len(wins) / len(closed_trades)) * 100, 2)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "starting_equity": starting_equity,
            "latest_equity": latest_equity,
            "highest_equity": highest_equity,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": PaperDrawdownEngine().calculate().get("max_drawdown_pct", 0),
            "snapshot_count": 1,
            "paper_trade_count": len(trades),
            "open_trade_count": len(open_trades),
            "closed_trade_count": len(closed_trades),
            "symbols_traded": symbols,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": win_rate_pct,
            "status": "PERFORMANCE_SUMMARY_READY"
        }
