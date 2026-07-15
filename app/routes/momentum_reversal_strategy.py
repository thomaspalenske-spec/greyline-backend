from fastapi import APIRouter

from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine

router = APIRouter()


@router.get("/momentum-reversal-strategy")
def momentum_reversal_strategy(top_n: int = 5):
    """The rebuilt validated strategy's current target positions (dry run, no trades)."""
    return MomentumReversalStrategyEngine(top_n=top_n).run()
