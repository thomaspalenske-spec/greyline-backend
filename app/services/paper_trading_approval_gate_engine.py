from datetime import datetime


class PaperTradingApprovalGateEngine:

    def evaluate_approval(
        self,
        paper_trading_ready,
        manual_approval_granted
    ):

        approval_passed = (
            paper_trading_ready
            and manual_approval_granted
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trading_ready": paper_trading_ready,
            "manual_approval_granted": manual_approval_granted,
            "approval_passed": approval_passed,
            "next_state": (
                "PAPER_TRADING_ALLOWED"
                if approval_passed
                else "PAPER_TRADING_ALLOWED"
            )
        }
