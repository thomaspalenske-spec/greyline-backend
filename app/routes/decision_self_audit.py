from fastapi import APIRouter
from app.services.decision_self_audit_engine import DecisionSelfAuditEngine

router = APIRouter()

@router.get("/decision-self-audit")
def decision_self_audit():
    return DecisionSelfAuditEngine().analyze()
