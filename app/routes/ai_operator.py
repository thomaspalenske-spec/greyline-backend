from app.services.paper_trade_lifecycle_engine import PaperTradeLifecycleEngine
from app.services.paper_trade_candidate_engine import PaperTradeCandidateEngine
from app.services.deployment_governance_layer import DeploymentGovernanceLayer
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.tradestation_token_status_engine import TradeStationTokenStatusEngine
from app.services.options_cycle_engine import OptionsCycleEngine
from app.services.options_account_dashboard_engine import OptionsAccountDashboardEngine
from app.services.options_position_manager_engine import OptionsPositionManagerEngine
from app.services.tradestation_sandbox_readiness_engine import TradeStationSandboxReadinessEngine
from app.services.live_broker_health_engine import LiveBrokerHealthEngine
from app.services.live_broker_summary_engine import LiveBrokerSummaryEngine
from app.services.live_trade_authority_gate_engine import LiveTradeAuthorityGateEngine
from app.services.pre_trade_risk_gate_engine import PreTradeRiskGateEngine
from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.routes.paper_trade_executor import run_paper_trade_executor
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine
from app.services.fast_quote_heartbeat_service import FastQuoteHeartbeatService

router = APIRouter()


def safe_call(name, fn):
    try:
        return {"ok": True, "name": name, "data": fn()}
    except Exception as e:
        return {"ok": False, "name": name, "error": str(e)}


@router.get("/ai-operator-brief")
def ai_operator_brief():
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "source": "AI_OPERATOR_BRIEF",
        "purpose": "Single endpoint for ChatGPT-assisted GreyLine status review",
        "live_broker_health": safe_call(
            "live_broker_health",
            lambda: LiveBrokerHealthEngine().evaluate()
        ),
        "live_broker_summary": safe_call(
            "live_broker_summary",
            lambda: LiveBrokerSummaryEngine().summarize()
        ),
        "tradestation_token_status": safe_call(
            "tradestation_token_status",
            lambda: TradeStationTokenStatusEngine().evaluate()
        ),
        "tradestation_sandbox_readiness": safe_call(
            "tradestation_sandbox_readiness",
            lambda: TradeStationSandboxReadinessEngine().evaluate()
        ),
        "pre_trade_risk_gate": safe_call(
            "pre_trade_risk_gate",
            lambda: PreTradeRiskGateEngine().evaluate()
        ),
        "live_trade_authority_gate": safe_call(
            "live_trade_authority_gate",
            lambda: LiveTradeAuthorityGateEngine().evaluate()
        ),
        "greyline_master_decision": safe_call(
            "greyline_master_decision",
            lambda: GreyLineMasterDecisionEngine().evaluate()
        ),
        "audit_ledger_summary": safe_call(
            "audit_ledger_summary",
            lambda: ImmutableAuditLedgerEngine().summary()
        ),
        "fast_quote_heartbeat": safe_call(
            "fast_quote_heartbeat",
            lambda: FastQuoteHeartbeatService.status()
        ),
        "execution_policy": {
            "live_order_placement_allowed": False,
            "ai_direct_live_trading_allowed": False,
            "safe_ai_actions": [
                "STATUS_REVIEW",
                "READINESS_REVIEW",
                "RISK_REVIEW",
                "PAPER_TRADING_REVIEW"
            ]
        },
        "status": "AI_OPERATOR_BRIEF_READY"
    }


class AICommandRequest(BaseModel):
    command: str


@router.post("/ai-command")
def ai_command(request: AICommandRequest):
    command = request.command.strip().upper()

    allowed = {
        "STATUS": lambda: ai_operator_brief(),
        "RUN_PAPER_TRADE_ENTRY": lambda: PaperTradeLifecycleEngine().entry(),
        "RUN_PAPER_TRADE_MARK_TO_MARKET": lambda: PaperTradeLifecycleEngine().mark_to_market(),
        "RUN_PAPER_TRADE_EXIT": lambda: PaperTradeLifecycleEngine().exit(),
        "RUN_PAPER_TRADE_CANDIDATE": lambda: PaperTradeCandidateEngine().build_ticket(),
        "RUN_MASTER_DECISION": lambda: (
    lambda decision, dgl: {
        **decision,
        "deployment_governance": dgl,
        "paper_trade_promotion": {
            "eligible": (
                decision.get("top_candidate", {}).get("result") == "WATCH"
                and dgl.get("deployment_state") in ["READY", "EXECUTE", "EXECUTE_AGGRESSIVE"]
                and decision.get("order_placement_allowed") is False
            ),
            "promoted_state": (
                "READY_FOR_PAPER_TRADE"
                if (
                    decision.get("top_candidate", {}).get("result") == "WATCH"
                    and dgl.get("deployment_state") in ["READY", "EXECUTE", "EXECUTE_AGGRESSIVE"]
                    and decision.get("order_placement_allowed") is False
                )
                else "NO_PROMOTION"
            ),
            "reason": "Candidate is actionable at reduced size, but live order placement is disabled."
        }
    }
)(GreyLineMasterDecisionEngine().evaluate(), DeploymentGovernanceLayer().score()),
        "RUN_PAPER_TRADE_EXECUTOR": lambda: run_paper_trade_executor(),
        "RUN_OPTIONS_CYCLE": lambda: OptionsCycleEngine().run(),
        "RUN_OPTIONS_STATUS": lambda: OptionsAccountDashboardEngine().get_dashboard(),
        "RUN_OPTIONS_MANAGER": lambda: OptionsPositionManagerEngine().manage_open_positions(),
        "RUN_PRE_TRADE_RISK_GATE": lambda: PreTradeRiskGateEngine().evaluate(),
        "RUN_LIVE_AUTHORITY_GATE": lambda: LiveTradeAuthorityGateEngine().evaluate(),
        "RUN_SANDBOX_READINESS": lambda: TradeStationSandboxReadinessEngine().evaluate(),
        "RUN_TOKEN_STATUS": lambda: TradeStationTokenStatusEngine().evaluate(),
    }

    if command not in allowed:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "AI_COMMAND",
            "command": command,
            "accepted": False,
            "reason": "Command not allowed",
            "allowed_commands": sorted(list(allowed.keys())),
            "live_order_placement_allowed": False,
            "status": "AI_COMMAND_REJECTED"
        }

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "source": "AI_COMMAND",
        "command": command,
        "accepted": True,
        "live_order_placement_allowed": False,
        "result": allowed[command](),
        "status": "AI_COMMAND_COMPLETE"
    }
