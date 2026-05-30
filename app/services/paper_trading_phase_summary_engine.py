from datetime import datetime


class PaperTradingPhaseSummaryEngine:

    def get_phase_summary(self):

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "current_phase": "PAPER_TRADING_PREP",
            "paper_trading_ready": False,
            "paper_trading_blocked": True,
            "approval_passed": False,
            "final_gate_passed": False,
            "command_center": "ACTIVE",
            "next_action": "COMPLETE_PAPER_TRADING_BLOCKERS",
            "status": "PAPER_TRADING_PHASE_SUMMARY_ACTIVE"
        }
