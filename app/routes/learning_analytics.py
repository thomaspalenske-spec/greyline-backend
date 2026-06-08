from fastapi import APIRouter
from app.services.learning_analytics_engine import LearningAnalyticsEngine

router = APIRouter()

@router.get("/learning-analytics")
def learning_analytics():
    return LearningAnalyticsEngine().summarize()
