from fastapi import APIRouter
from app.services.decision_feature_attribution_engine import DecisionFeatureAttributionEngine

router = APIRouter()

@router.get("/decision-feature-attribution")
def decision_feature_attribution():
    return DecisionFeatureAttributionEngine().analyze()
