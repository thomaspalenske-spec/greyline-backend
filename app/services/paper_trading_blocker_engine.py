from datetime import datetime


class PaperTradingBlockerEngine:

    def evaluate_blockers(self):

        blockers = [
            "TradeStation API credentials not configured",
            "Paper trading account not verified",
            "Broker sandbox not connected",
            "Reconciliation testing not completed against broker data",
            "Kill switch not tested against broker workflow",
            "Manual approval not granted for paper trading deployment"
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trading_blocked": True,
            "blockers": blockers,
            "blocker_count": len(blockers),
            "status": "PAPER_TRADING_ALLOWED"
        }
