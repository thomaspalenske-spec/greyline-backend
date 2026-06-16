from datetime import datetime

from app.services.paper_equity_timeline_engine import (
    PaperEquityTimelineEngine
)
from app.services.paper_drawdown_engine import (
    PaperDrawdownEngine
)
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


class PaperPerformanceSummaryEngine:

    def summarize(self):

        timeline = (
            PaperEquityTimelineEngine()
            .build_timeline()
        )

        drawdown = (
            PaperDrawdownEngine()
            .calculate()
        )

        ledger = PaperTradeLedgerEngine().history(limit=10000)
        trades = ledger.get("trades", [])
        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        closed_trades = [t for t in trades if t.get("status") == "CLOSED"]
        symbols = sorted(list(set(t.get("symbol") for t in trades if t.get("symbol"))))

        latest_equity = timeline.get(
            "latest_equity",
            0
        )

        highest_equity = timeline.get(
            "highest_equity",
            0
        )

        starting_equity = (
            timeline["timeline"][0]["equity"]
            if timeline.get("timeline")
            else 0
        )

        total_return_pct = 0

        if starting_equity > 0:
            total_return_pct = (
                (
                    latest_equity
                    - starting_equity
                )
                / starting_equity
            ) * 100

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "starting_equity": starting_equity,
            "latest_equity": latest_equity,
            "highest_equity": highest_equity,
            "total_return_pct": round(
                total_return_pct,
                2
            ),
            "max_drawdown_pct":
                drawdown.get(
                    "max_drawdown_pct",
                    0
                ),
            "snapshot_count":
                timeline.get(
                    "snapshot_count",
                    0
                ),
            "paper_trade_count": len(trades),
            "open_trade_count": len(open_trades),
            "closed_trade_count": len(closed_trades),
            "symbols_traded": symbols,
            "win_count": 0,
            "loss_count": 0,
            "win_rate_pct": 0,
            "status":
                "PERFORMANCE_SUMMARY_READY"
        }
