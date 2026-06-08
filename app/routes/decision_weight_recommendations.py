from fastapi import APIRouter
from app.services.decision_weight_recommendation_engine import (
    DecisionWeightRecommendationEngine,
)

router = APIRouter()

@router.get("/decision-weight-recommendations")
def decision_weight_recommendations():
    return DecisionWeightRecommendationEngine().recommend()
