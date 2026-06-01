from datetime import datetime


class PaperTradingTransitionSummaryEngine:

    def summarize_transition(
        self,
        paper_trading_ready,
        approval_passed,
        broker_connected,
        api_credentials_configured
    ):

        transition_allowed = (
            paper_trading_ready
            and approval_passed
            and broker_connected
            and api_credentials_configured
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trading_ready": paper_trading_ready,
            "approval_passed": approval_passed,
            "broker_connected": broker_connected,
            "api_credentials_configured": api_credentials_configured,
            "transition_allowed": transition_allowed,
            "next_state": (
                "PAPER_TRADING_ALLOWED"
                if transition_allowed
                else "PAPER_TRADING_ALLOWED"
            )
        }
