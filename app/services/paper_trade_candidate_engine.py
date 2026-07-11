from datetime import datetime
from app.services.greyline_master_decision_engine import GreyLineMasterDecisionEngine
from app.services.deployment_governance_layer import DeploymentGovernanceLayer
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class PaperTradeCandidateEngine:
    """
    Builds a simulated paper-trade ticket from GreyLine's top candidate.
    This does not place live orders.
    """

    def build_ticket(self):
        decision = GreyLineMasterDecisionEngine().evaluate()
        dgl = DeploymentGovernanceLayer().score(symbol=decision.get("top_candidate", {}).get("symbol"))

        candidate = decision.get("top_candidate", {})
        regime_calibration = (
            candidate.get("regime_calibration") or {}
        )
        regime_execution_allowed = bool(
            regime_calibration.get(
                "execution_allowed",
                True,
            )
        )
        regime_position_multiplier = float(
            regime_calibration.get(
                "position_multiplier",
                1.0,
            )
            or 1.0
        )

        base_position_size_pct = float(
            dgl.get("recommended_position_size_pct")
            or 0.0
        )
        calibrated_position_size_pct = round(
            base_position_size_pct
            * regime_position_multiplier,
            6,
        )

        eligible = (
            candidate.get("result") in ["WATCH", "EXECUTE"]
            and regime_execution_allowed
            and dgl.get("deployment_state") in ["READY", "EXECUTE", "EXECUTE_AGGRESSIVE"]
            and decision.get("order_placement_allowed") is False
        )

        if not eligible:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "engine": "PaperTradeCandidateEngine",
                "paper_trade_ticket_created": False,
                "reason": (
                    "REGIME_CALIBRATION_BLOCKED"
                    if not regime_execution_allowed
                    else "No candidate eligible for paper trade promotion."
                ),
                "regime_calibration": regime_calibration,
                "regime_execution_allowed": (
                    regime_execution_allowed
                ),
                "regime_position_multiplier": (
                    regime_position_multiplier
                ),
                "decision": decision,
                "deployment_governance": dgl,
                "live_order_placement_attempted": False,
                "status": "NO_PAPER_TRADE_CANDIDATE",
            }

        ticket = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "PaperTradeCandidateEngine",
            "paper_trade_ticket_created": True,
            "ticket_type": "SIMULATED_PAPER_TRADE",
            "symbol": candidate.get("symbol"),
            "side": "BUY",
            "directional_bias": candidate.get("directional_bias"),
            "option_type": candidate.get("option_type"),
            "trade_intent": "BUY_CALL" if candidate.get("option_type") == "CALL" else "BUY_PUT" if candidate.get("option_type") == "PUT" else "UNKNOWN",
            "bullish_score": candidate.get("bullish_score"),
            "bearish_score": candidate.get("bearish_score"),
            "opposing_score": candidate.get("opposing_score"),
            "direction_confidence": candidate.get("direction_confidence"),
            "candidate_original_state": candidate.get("result"),
            "promoted_state": "READY_FOR_PAPER_TRADE",
            "composite_score": candidate.get("composite_score"),
            "deployment_score": dgl.get("deployment_score"),
            "base_recommended_position_size_pct": (
                base_position_size_pct
            ),
            "recommended_position_size_pct": (
                calibrated_position_size_pct
            ),
            "regime_calibration": regime_calibration,
            "regime_calibration_state": (
                regime_calibration.get("state")
            ),
            "regime_calibration_actionable": (
                regime_calibration.get("actionable")
            ),
            "regime_position_multiplier": (
                regime_position_multiplier
            ),
            "regime_execution_allowed": (
                regime_execution_allowed
            ),
            "regime_confidence_adjustment": (
                regime_calibration.get(
                    "confidence_adjustment"
                )
            ),
            "regime_composite_adjustment": (
                regime_calibration.get(
                    "composite_adjustment"
                )
            ),
            "order_placement_allowed": False,
            "live_order_placement_attempted": False,
            "execution_mode": "PAPER_ONLY",
            "status": "PAPER_TRADE_TICKET_READY",
        }

        audit_result = ImmutableAuditLedgerEngine().record(
            "PAPER_TRADE_TICKET_CREATED",
            ticket
        )

        ticket["audit_logged"] = True
        ticket["audit_result"] = audit_result

        return ticket
