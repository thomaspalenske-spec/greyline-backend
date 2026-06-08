import json
from datetime import datetime
from pathlib import Path

from app.services.decision_weight_recommendation_engine import (
    DecisionWeightRecommendationEngine,
)
from app.services.immutable_audit_ledger_engine import ImmutableAuditLedgerEngine


class AdaptiveWeightGovernanceEngine:

    def __init__(self):
        self.log_dir = Path("app/data/adaptive_governance")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.proposal_file = self.log_dir / "weight_change_proposals.jsonl"
        self.approval_file = self.log_dir / "weight_change_approvals.jsonl"

    def generate_proposals(self):
        recommendations = DecisionWeightRecommendationEngine().recommend()
        proposals = []

        for item in recommendations.get("recommendations", []):
            proposal = {
                "timestamp": datetime.utcnow().isoformat(),
                "proposal_id": f"{item.get('factor')}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                "factor": item.get("factor"),
                "recommended_action": item.get("recommendation"),
                "rationale": item.get("rationale"),
                "failures": item.get("failures"),
                "successes": item.get("successes"),
                "status": "PENDING_HUMAN_APPROVAL",
                "automatic_weight_changes_enabled": False,
                "human_approval_required": True,
                "execution_enabled": False,
                "order_placement_allowed": False,
            }
            proposals.append(proposal)

        with self.proposal_file.open("a") as f:
            for proposal in proposals:
                f.write(json.dumps(proposal) + "\n")

                ImmutableAuditLedgerEngine().record(
                    "GOVERNANCE_PROPOSAL",
                    {
                        "proposal_id": proposal.get("proposal_id"),
                        "factor": proposal.get("factor"),
                        "recommended_action": proposal.get("recommended_action"),
                        "failures": proposal.get("failures"),
                        "successes": proposal.get("successes"),
                    },
                )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "ADAPTIVE_WEIGHT_GOVERNANCE",
            "proposals_generated": len(proposals),
            "proposals": proposals,
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "WEIGHT_CHANGE_PROPOSALS_READY",
        }

    def get_proposals(self, limit=50):
        proposals = self._read_jsonl(self.proposal_file, limit=limit)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "ADAPTIVE_WEIGHT_GOVERNANCE",
            "proposal_count": len(proposals),
            "proposals": proposals,
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "WEIGHT_CHANGE_PROPOSALS_HISTORY_READY",
        }

    def approve_proposal(self, proposal_id=None, approver="operator"):
        if not proposal_id:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "approved": False,
                "reason": "proposal_id required",
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "WEIGHT_CHANGE_APPROVAL_REJECTED",
            }

        proposals = self._read_jsonl(self.proposal_file, limit=500)
        match = next(
            (item for item in proposals if item.get("proposal_id") == proposal_id),
            None,
        )

        if not match:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "approved": False,
                "proposal_id": proposal_id,
                "reason": "proposal_id not found",
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": "WEIGHT_CHANGE_APPROVAL_NOT_FOUND",
            }

        approval = {
            "timestamp": datetime.utcnow().isoformat(),
            "proposal_id": proposal_id,
            "factor": match.get("factor"),
            "approved_action": match.get("recommended_action"),
            "approver": approver,
            "status": "APPROVED_FOR_FUTURE_WEIGHT_REGISTRY_UPDATE",
            "automatic_weight_changes_enabled": False,
            "execution_enabled": False,
            "order_placement_allowed": False,
        }

        with self.approval_file.open("a") as f:
            f.write(json.dumps(approval) + "\n")

        ImmutableAuditLedgerEngine().record(
            "GOVERNANCE_APPROVAL",
            {
                "proposal_id": approval.get("proposal_id"),
                "factor": approval.get("factor"),
                "approved_action": approval.get("approved_action"),
                "approver": approval.get("approver"),
            },
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "ADAPTIVE_WEIGHT_GOVERNANCE",
            "approved": True,
            "approval": approval,
            "automatic_weight_changes_enabled": False,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "WEIGHT_CHANGE_APPROVAL_RECORDED",
        }

    def active_governance(self, limit=50):
        approvals = self._read_jsonl(self.approval_file, limit=limit)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "ADAPTIVE_WEIGHT_GOVERNANCE",
            "approved_weight_changes": len(approvals),
            "approvals": approvals,
            "automatic_weight_changes_enabled": False,
            "human_approval_required": True,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "ACTIVE_WEIGHT_GOVERNANCE_READY",
        }

    def _read_jsonl(self, path, limit=50):
        if not path.exists():
            return []

        lines = path.read_text().splitlines()
        recent = lines[-limit:]

        rows = []
        for line in recent:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return rows
