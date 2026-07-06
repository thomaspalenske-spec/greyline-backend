from datetime import datetime

from app.services.paper_trading_readiness_engine import PaperTradingReadinessEngine


class PaperTradingBlockerEngine:

    def evaluate_blockers(self):
        readiness = PaperTradingReadinessEngine().evaluate_readiness()

        checks = [
            (
                readiness.get("api_credentials_configured") is True,
                "TradeStation API credentials not configured",
            ),
            (
                readiness.get("paper_account_verified") is True,
                "Paper trading account not verified",
            ),
            (
                readiness.get("broker_sandbox_connected") is True,
                "Broker sandbox not connected",
            ),
            (
                readiness.get("reconciliation_testing_complete") is True,
                "Reconciliation testing not completed against broker data",
            ),
            (
                readiness.get("kill_switch_testing_complete") is True,
                "Kill switch not tested against broker workflow",
            ),
            (
                readiness.get("manual_approval_granted") is True,
                "Manual approval not granted for paper trading deployment",
            ),
        ]

        blockers = [message for passed, message in checks if not passed]
        paper_trading_blocked = len(blockers) > 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trading_blocked": paper_trading_blocked,
            "paper_trading_ready": not paper_trading_blocked,
            "readiness": readiness,
            "blockers": blockers,
            "blocker_count": len(blockers),
            "status": (
                "PAPER_TRADING_BLOCKED"
                if paper_trading_blocked
                else "PAPER_TRADING_ALLOWED"
            ),
        }
