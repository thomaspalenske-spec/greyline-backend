from datetime import datetime

from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine


class ExecutionAuthorityEngine:
    """
    Single source of truth for execution authority.

    Separates:
    - market signal
    - reliability/governor authority
    - paper execution
    - live execution
    """

    def evaluate(self):
        decision = GreyLineMasterDecisionEngine().evaluate()
        governor = ReliabilityGovernorEngine().evaluate()

        signal = decision.get("decision")
        top = decision.get("top_candidate") or {}
        mode = governor.get("operating_mode")

        paper_allowed = False
        live_allowed = False
        authority = "NO_ACTION"
        reason = "No executable signal."

        if signal in ["EXECUTE", "EXECUTE_SIGNAL_BLOCKED_READ_ONLY"]:
            if mode == "PAPER_OPERATIONAL":
                paper_allowed = True
                live_allowed = False
                authority = "PAPER_EXECUTE"
                reason = "Signal executable. Paper execution allowed. Live order placement disabled."
            elif mode == "LIVE_OPERATIONAL":
                paper_allowed = True
                live_allowed = True
                authority = "LIVE_EXECUTE"
                reason = "Signal executable. Live execution allowed."
            else:
                authority = "BLOCKED"
                reason = f"Signal executable but governor mode is {mode}."

        elif signal == "WATCH":
            authority = "WATCH"
            reason = "Signal is watch only."

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ExecutionAuthorityEngine",
            "signal_decision": signal,
            "execution_authority": authority,
            "paper_execution_allowed": paper_allowed,
            "live_execution_allowed": live_allowed,
            "autonomous_execution_allowed": live_allowed,
            "governor_mode": mode,
            "reliability_score": governor.get("reliability_score"),
            "top_candidate": top,
            "reason": reason,
            "status": "EXECUTION_AUTHORITY_READY",
        }
