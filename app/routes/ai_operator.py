from app.services.paper_trade_lifecycle_engine import PaperTradeLifecycleEngine
from app.services.paper_trade_candidate_engine import PaperTradeCandidateEngine
from app.services.deployment_governance_layer import DeploymentGovernanceLayer
from datetime import datetime
import threading
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
from app.services.market_battlefield_snapshot_cache import MarketBattlefieldSnapshotCache
from app.routes.greyline_market_battlefield import greyline_market_battlefield
from app.routes.greyline_market_battlefield_summary import greyline_market_battlefield_summary
from app.services.opportunity_queue_engine import OpportunityQueueEngine
from app.routes.market_battlefield_forecast import market_battlefield_forecast

router = APIRouter()



_battlefield_refresh_state = {
    "running": False,
    "last_started_at": None,
    "last_completed_at": None,
    "last_duration_seconds": None,
    "last_status": "NEVER_RUN",
    "last_error": None,
}


def _battlefield_refresh_status():
    now = datetime.utcnow()
    state = dict(_battlefield_refresh_state)

    if state.get("running") is True and state.get("last_started_at"):
        try:
            started = datetime.fromisoformat(state["last_started_at"])
            running_seconds = round((now - started).total_seconds(), 2)
            state["running_seconds"] = running_seconds

            if running_seconds > 600:
                state["last_status"] = "STALE_RUNNING_REVIEW_REQUIRED"
                state["stale_running"] = True
                state["stale_threshold_seconds"] = 600
            else:
                state["stale_running"] = False
                state["stale_threshold_seconds"] = 600
        except Exception as e:
            state["running_seconds"] = None
            state["stale_running"] = None
            state["last_error"] = str(e)

    return {
        "timestamp": now.isoformat(),
        "system": "GreyLine",
        "refresh_target": "MARKET_BATTLEFIELD_SUMMARY",
        **state,
        "status": "MARKET_BATTLEFIELD_REFRESH_STATUS_READY",
    }

def safe_call(name, fn):
    try:
        return {"ok": True, "name": name, "data": fn()}
    except Exception as e:
        return {"ok": False, "name": name, "error": str(e)}



@router.get("/operator-quick-brief")
def operator_quick_brief():
    battlefield_summary = greyline_market_battlefield_summary()
    opportunity_queue = OpportunityQueueEngine().build(battlefield_summary)
    top_candidates = opportunity_queue.get("queue", [])[:3]
    top_candidate = top_candidates[0] if top_candidates else {}

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "source": "OPERATOR_QUICK_BRIEF",
        "battlefield_health": battlefield_summary.get("battlefield_health"),
        "battlefield_health_reason": battlefield_summary.get("battlefield_health_reason"),
        "top_candidate": top_candidate,
        "top_candidates": top_candidates,
        "opportunity_queue_status": opportunity_queue.get("status"),
        "token_status": safe_call(
            "tradestation_token_status",
            lambda: TradeStationTokenStatusEngine().evaluate()
        ),
        "live_broker_health": safe_call(
            "live_broker_health",
            lambda: LiveBrokerHealthEngine().evaluate()
        ),
        "live_trade_authority_gate": safe_call(
            "live_trade_authority_gate",
            lambda: LiveTradeAuthorityGateEngine().evaluate()
        ),
        "status": "OPERATOR_QUICK_BRIEF_READY",
    }

@router.get("/ai-operator-brief")
def ai_operator_brief():
    battlefield_summary = greyline_market_battlefield_summary()

    opportunity_queue = OpportunityQueueEngine().build(battlefield_summary)
    top_candidates = opportunity_queue.get("queue", [])[:3]
    top_candidate = top_candidates[0] if top_candidates else {}

    forecast_result = safe_call(
        "market_battlefield_forecast",
        lambda: market_battlefield_forecast()
    )
    forecast = forecast_result.get("data", {}) if forecast_result.get("ok") else {}
    queue_top = (forecast.get("opportunity_queue", {}) or {}).get("top_candidate", {}) or {}
    prediction_accuracy = forecast.get("battlefield_prediction_accuracy", {}) or {}
    confidence_calibration = forecast.get("confidence_calibration", {}) or {}

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
        "market_battlefield_summary": safe_call(
            "market_battlefield_summary",
            lambda: greyline_market_battlefield_summary()
        ),
        "market_battlefield_forecast": forecast_result,

        "operator_top_candidate": {
            "symbol": queue_top.get("symbol") or top_candidate.get("symbol"),
            "score": queue_top.get("score") or top_candidate.get("score"),
            "adjusted_score": queue_top.get("adjusted_score"),
            "signal_age_days": (queue_top.get("signal_decay", {}) or {}).get("signal_age_days") or top_candidate.get("signal_age_days"),
            "signal_strength_score": (queue_top.get("signal_decay", {}) or {}).get("signal_strength_score"),
            "signal_state": (queue_top.get("signal_decay", {}) or {}).get("signal_state"),
            "signal_decay_penalty": queue_top.get("signal_decay_penalty"),
            "signal_decay_reason": queue_top.get("signal_decay_reason"),
            "option_type": queue_top.get("option_type") or top_candidate.get("option_type"),
            "directional_bias": queue_top.get("directional_bias") or top_candidate.get("directional_bias"),
            "historical_accuracy_pct": prediction_accuracy.get("accuracy_pct") or prediction_accuracy.get("overall_accuracy_pct"),
            "confidence_level": confidence_calibration.get("confidence_level"),
            "historical_win_rate_pct": confidence_calibration.get("historical_win_rate_pct"),
        },
        "greyline_master_decision": {
            "ok": True,
            "name": "greyline_master_decision",
            "data": {
                "status": "SKIPPED_IN_FAST_BRIEF",
                "reason": "Master decision is intentionally excluded from /ai-operator-brief because it can take 60+ seconds.",
                "run_full_check_with": "POST /ai-command {command: RUN_MASTER_DECISION}"
            }
        },
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


def _run_master_decision_with_governance():
    decision = GreyLineMasterDecisionEngine().evaluate()
    dgl = DeploymentGovernanceLayer().score(symbol=decision.get("top_candidate", {}).get("symbol"))

    decision["deployment_governance"] = dgl
    decision["paper_trade_promotion"] = {
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
    return decision


def _run_battlefield_summary_refresh_background():
    if _battlefield_refresh_state["running"] is True:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "background_refresh_started": False,
            "reason": "REFRESH_ALREADY_RUNNING",
            "refresh_status": _battlefield_refresh_status(),
            "status": "MARKET_BATTLEFIELD_BACKGROUND_REFRESH_ALREADY_RUNNING",
        }

    def worker():
        started = datetime.utcnow()
        _battlefield_refresh_state["running"] = True
        _battlefield_refresh_state["last_started_at"] = started.isoformat()
        _battlefield_refresh_state["last_completed_at"] = None
        _battlefield_refresh_state["last_duration_seconds"] = None
        _battlefield_refresh_state["last_status"] = "RUNNING"
        _battlefield_refresh_state["last_error"] = None

        try:
            greyline_market_battlefield_summary(force_refresh=True)
            completed = datetime.utcnow()
            _battlefield_refresh_state["last_completed_at"] = completed.isoformat()
            _battlefield_refresh_state["last_duration_seconds"] = round((completed - started).total_seconds(), 2)
            _battlefield_refresh_state["last_status"] = "COMPLETED"
        except Exception as e:
            completed = datetime.utcnow()
            _battlefield_refresh_state["last_completed_at"] = completed.isoformat()
            _battlefield_refresh_state["last_duration_seconds"] = round((completed - started).total_seconds(), 2)
            _battlefield_refresh_state["last_status"] = "FAILED"
            _battlefield_refresh_state["last_error"] = str(e)
        finally:
            _battlefield_refresh_state["running"] = False

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "system": "GreyLine",
        "background_refresh_started": True,
        "refresh_target": "MARKET_BATTLEFIELD_SUMMARY",
        "refresh_status": _battlefield_refresh_status(),
        "status": "MARKET_BATTLEFIELD_BACKGROUND_REFRESH_STARTED"
    }



def _run_options_cycle_for_battlefield_top_candidate():
    battlefield_summary = greyline_market_battlefield_summary()
    opportunity_queue = OpportunityQueueEngine().build(battlefield_summary)
    top_candidate = opportunity_queue.get("top_candidate") or {}

    symbol = top_candidate.get("symbol")
    option_type = top_candidate.get("option_type") or "CALL"

    if not symbol:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_CYCLE_BATTLEFIELD",
            "paper_trade_recorded": False,
            "reason": "NO_BATTLEFIELD_TOP_CANDIDATE",
            "status": "OPTIONS_CYCLE_BATTLEFIELD_NO_ACTION",
        }

    if top_candidate.get("result") != "EXECUTE":
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_CYCLE_BATTLEFIELD",
            "paper_trade_recorded": False,
            "symbol": symbol,
            "option_type": option_type,
            "candidate_result": top_candidate.get("result"),
            "reason": "TOP_CANDIDATE_NOT_EXECUTE",
            "status": "OPTIONS_CYCLE_BATTLEFIELD_NOT_READY",
        }

    result = OptionsCycleEngine().run(
        symbol=symbol,
        option_type=option_type,
    )

    result["battlefield_top_candidate"] = top_candidate
    result["source"] = "OPTIONS_CYCLE_BATTLEFIELD"
    return result

@router.post("/ai-command")


def ai_command(request: AICommandRequest):
    command = request.command.strip().upper()

    allowed = {
        "STATUS": lambda: ai_operator_brief(),
        "RUN_PAPER_TRADE_ENTRY": lambda: PaperTradeLifecycleEngine().entry(),
        "RUN_PAPER_TRADE_MARK_TO_MARKET": lambda: PaperTradeLifecycleEngine().mark_to_market(),
        "RUN_PAPER_TRADE_EXIT": lambda: PaperTradeLifecycleEngine().exit(),
        "RUN_PAPER_TRADE_CANDIDATE": lambda: PaperTradeCandidateEngine().build_ticket(),
        "RUN_MASTER_DECISION": lambda: _run_master_decision_with_governance(),
        "RUN_MARKET_BATTLEFIELD": lambda: greyline_market_battlefield(),
        "RUN_MARKET_BATTLEFIELD_SUMMARY": lambda: greyline_market_battlefield_summary(),
        "RUN_MARKET_BATTLEFIELD_SUMMARY_REFRESH": lambda: greyline_market_battlefield_summary(force_refresh=True),
        "RUN_MARKET_BATTLEFIELD_SUMMARY_REFRESH_BACKGROUND": lambda: _run_battlefield_summary_refresh_background(),
        "RUN_MARKET_BATTLEFIELD_REFRESH_STATUS": lambda: _battlefield_refresh_status(),
        "RUN_MARKET_BATTLEFIELD_CACHE_CLEAR": lambda: MarketBattlefieldSnapshotCache.clear(),
        "RUN_PAPER_TRADE_EXECUTOR": lambda: run_paper_trade_executor(),
        "RUN_OPTIONS_CYCLE": lambda: _run_options_cycle_for_battlefield_top_candidate(),
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

    command_started_at = datetime.utcnow()
    result = allowed[command]()
    command_completed_at = datetime.utcnow()
    command_duration_seconds = round(
        (command_completed_at - command_started_at).total_seconds(),
        2
    )

    return {
        "timestamp": command_completed_at.isoformat(),
        "command_started_at": command_started_at.isoformat(),
        "command_completed_at": command_completed_at.isoformat(),
        "command_duration_seconds": command_duration_seconds,
        "system": "GreyLine",
        "source": "AI_COMMAND",
        "command": command,
        "accepted": True,
        "live_order_placement_allowed": False,
        "result": result,
        "status": "AI_COMMAND_COMPLETE"
    }
