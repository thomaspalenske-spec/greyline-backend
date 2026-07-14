from fastapi import APIRouter

from app.services.per_feed_skill_engine import PerFeedSkillEngine

router = APIRouter()


@router.get("/feature-skill")
def feature_skill(horizon_hours: float = 24.0):
    return PerFeedSkillEngine(horizon_hours=horizon_hours).evaluate()
