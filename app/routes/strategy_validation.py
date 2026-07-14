from fastapi import APIRouter

from app.services.strategy_validation_engine import StrategyValidationEngine

router = APIRouter()


@router.get("/strategy-validation")
def strategy_validation(limit: int = 1000):
    return StrategyValidationEngine().validate(limit=limit)
