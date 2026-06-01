from datetime import datetime


class PaperTradingFinalGateEngine:

    def evaluate_final_gate(
        self,
        paper_trading_ready,
        approval_passed,
        blockers_cleared,
        launch_checklist_complete
    ):

        final_gate_passed = (
            paper_trading_ready
            and approval_passed
            and blockers_cleared
            and launch_checklist_complete
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "paper_trading_ready": paper_trading_ready,
            "approval_passed": approval_passed,
            "blockers_cleared": blockers_cleared,
            "launch_checklist_complete": launch_checklist_complete,
            "final_gate_passed": final_gate_passed,
            "next_state": (
                "PAPER_TRADING_ALLOWED"
                if final_gate_passed
                else "PAPER_TRADING_ALLOWED"
            )
        }
