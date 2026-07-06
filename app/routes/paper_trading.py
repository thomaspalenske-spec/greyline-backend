from fastapi import APIRouter

from app.services.paper_trading_command_center_engine import PaperTradingCommandCenterEngine

router = APIRouter()


@router.get("/paper-trading-command-center")
def paper_trading_command_center():
    engine = PaperTradingCommandCenterEngine()
    return engine.get_command_center()


from app.services.paper_trading_prep_gate_engine import PaperTradingPrepGateEngine
from app.services.paper_trading_blocker_engine import PaperTradingBlockerEngine
from app.services.paper_trading_approval_gate_engine import PaperTradingApprovalGateEngine
from app.services.paper_trading_control_center_engine import PaperTradingControlCenterEngine
from app.services.paper_trading_transition_summary_engine import PaperTradingTransitionSummaryEngine
from app.services.paper_trading_launch_checklist_engine import PaperTradingLaunchChecklistEngine
from app.services.paper_trading_final_gate_engine import PaperTradingFinalGateEngine
from app.services.paper_trading_phase_summary_engine import PaperTradingPhaseSummaryEngine


@router.get("/paper-trading-prep-gate")
def paper_trading_prep_gate():
    return PaperTradingPrepGateEngine().evaluate_prep_gate(
        backend_ready=True,
        broker_safety_ready=True,
        credential_safety_ready=True,
        authority_gate_ready=True,
        kill_switch_ready=True
    )


@router.get("/paper-trading-blockers")
def paper_trading_blockers():
    return PaperTradingBlockerEngine().evaluate_blockers()


@router.get("/paper-trading-approval-gate")
def paper_trading_approval_gate():
    blockers = PaperTradingBlockerEngine().evaluate_blockers()
    paper_trading_ready = not blockers.get("paper_trading_blocked", True)

    readiness = blockers.get("readiness", {})

    return PaperTradingApprovalGateEngine().evaluate_approval(
        paper_trading_ready=paper_trading_ready,
        manual_approval_granted=readiness.get("manual_approval_granted", False)
    )


@router.get("/paper-trading-control-center")
def paper_trading_control_center():
    return PaperTradingControlCenterEngine().get_control_center()


@router.get("/paper-trading-transition-summary")
def paper_trading_transition_summary():
    blockers = PaperTradingBlockerEngine().evaluate_blockers()
    approval = paper_trading_approval_gate()

    blocker_names = blockers.get("blockers", [])
    paper_trading_ready = not blockers.get("paper_trading_blocked", True)
    broker_connected = "Broker sandbox not connected" not in blocker_names
    api_credentials_configured = "TradeStation API credentials not configured" not in blocker_names

    return PaperTradingTransitionSummaryEngine().summarize_transition(
        paper_trading_ready=paper_trading_ready,
        approval_passed=approval.get("approval_passed", False),
        broker_connected=broker_connected,
        api_credentials_configured=api_credentials_configured
    )


@router.get("/paper-trading-launch-checklist")
def paper_trading_launch_checklist():
    return PaperTradingLaunchChecklistEngine().get_checklist()


@router.get("/paper-trading-final-gate")
def paper_trading_final_gate():
    blockers = PaperTradingBlockerEngine().evaluate_blockers()
    approval = paper_trading_approval_gate()
    checklist = PaperTradingLaunchChecklistEngine().get_checklist()

    paper_trading_ready = not blockers.get("paper_trading_blocked", True)
    blockers_cleared = blockers.get("blocker_count", 0) == 0
    launch_checklist_complete = checklist.get("launch_ready", False)

    return PaperTradingFinalGateEngine().evaluate_final_gate(
        paper_trading_ready=paper_trading_ready,
        approval_passed=approval.get("approval_passed", False),
        blockers_cleared=blockers_cleared,
        launch_checklist_complete=launch_checklist_complete
    )


@router.get("/paper-trading-phase-summary")
def paper_trading_phase_summary():
    return PaperTradingPhaseSummaryEngine().get_phase_summary()
