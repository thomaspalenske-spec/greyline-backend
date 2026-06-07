from fastapi import APIRouter
from app.services.decision_validation_engine import DecisionValidationEngine

router = APIRouter()

@router.get("/decision-validation")
def decision_validation():
    return DecisionValidationEngine().validate()
