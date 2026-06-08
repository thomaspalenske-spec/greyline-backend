from fastapi import APIRouter, Query
from app.services.adaptive_weight_governance_engine import (
    AdaptiveWeightGovernanceEngine,
)

router = APIRouter()

@router.post("/weight-change-proposals")
def weight_change_proposals():
    return AdaptiveWeightGovernanceEngine().generate_proposals()

@router.get("/weight-change-proposals")
def get_weight_change_proposals():
    return AdaptiveWeightGovernanceEngine().get_proposals()

@router.post("/approve-weight-change")
def approve_weight_change(
    proposal_id: str = Query(...),
    approver: str = Query("operator"),
):
    return AdaptiveWeightGovernanceEngine().approve_proposal(
        proposal_id=proposal_id,
        approver=approver,
    )

@router.get("/active-weight-governance")
def active_weight_governance():
    return AdaptiveWeightGovernanceEngine().active_governance()
