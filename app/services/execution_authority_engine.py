from datetime import datetime

from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.reliability_governor_engine import ReliabilityGovernorEngine
from app.services.execution_governor import ExecutionGovernor


class ExecutionAuthorityEngine:
    """
    Single source of truth for execution authority.

    Separates:
    - market signal
    - reliability/governor authority
    - paper execution
    - live execution

    The ExecutionGovernor env flags act as a hard kill-switch layered on top of
    signal + reliability authority: if GREYLINE_PAPER_EXECUTION_ENABLED is not
    true, paper execution is denied even when the signal and governor mode would
    otherwise permit it. This keeps the "execution enabled" surface reported by
    status endpoints authoritative over the code paths that actually record trades.
    """

    def evaluate(self, decision=None):
        """Evaluate execution authority.

        Execution paths call this with no argument: they need a *fresh* decision,
        because authority must be judged against the market as it is at the moment a
        trade would be recorded.

        Display/status routes should pass the already-recorded decision instead.
        GreyLineMasterDecisionEngine().evaluate() is a full scoring cycle that also
        appends to the decision audit log, so re-running it just to render a status
        panel both costs seconds per poll and writes trading decisions that no engine
        asked for.
        """
        if decision is None:
            decision = GreyLineMasterDecisionEngine().evaluate()
        governor = ReliabilityGovernorEngine().evaluate()
        permission = ExecutionGovernor().evaluate_execution_permission("EXECUTE")

        paper_execution_enabled = permission.get("paper_execution_enabled") is True
        live_execution_enabled = (
            permission.get("live_trading_enabled") is True
            and permission.get("live_order_placement_allowed") is True
        )

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

        # Hard kill-switch: env flags override signal/mode authority. A disabled
        # flag must stop trades from being recorded, not merely change a report.
        if paper_allowed and not paper_execution_enabled:
            paper_allowed = False
            live_allowed = False
            authority = "KILL_SWITCH_BLOCKED"
            reason = (
                "Signal and governor authorize execution, but paper execution is "
                "disabled by GREYLINE_PAPER_EXECUTION_ENABLED kill-switch."
            )
        elif live_allowed and not live_execution_enabled:
            live_allowed = False
            authority = "PAPER_EXECUTE"
            reason = (
                "Signal executable. Paper execution allowed. Live order placement "
                "disabled by GREYLINE_LIVE_* kill-switch."
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ExecutionAuthorityEngine",
            "signal_decision": signal,
            "execution_authority": authority,
            "paper_execution_allowed": paper_allowed,
            "live_execution_allowed": live_allowed,
            "autonomous_execution_allowed": live_allowed,
            "paper_execution_enabled": paper_execution_enabled,
            "live_execution_enabled": live_execution_enabled,
            "governor_mode": mode,
            "reliability_score": governor.get("reliability_score"),
            "top_candidate": top,
            "reason": reason,
            "status": "EXECUTION_AUTHORITY_READY",
        }
