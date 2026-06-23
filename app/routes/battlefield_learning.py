from fastapi import APIRouter

from app.services.battlefield_learning_ledger_engine import BattlefieldLearningLedgerEngine

router = APIRouter(tags=["Battlefield Learning"])


@router.get("/battlefield-learning-ledger")
def battlefield_learning_ledger():
    return BattlefieldLearningLedgerEngine().history(limit=250)
