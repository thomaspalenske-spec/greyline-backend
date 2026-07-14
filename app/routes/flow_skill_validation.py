from fastapi import APIRouter

from app.services.flow_skill_validation_engine import FlowSkillValidationEngine

router = APIRouter()


@router.get("/flow-skill-validation")
def flow_skill_validation(horizon_hours: float = 24.0):
    return FlowSkillValidationEngine(horizon_hours=horizon_hours).validate()
