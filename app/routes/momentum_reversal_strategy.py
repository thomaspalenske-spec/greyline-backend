from fastapi import APIRouter

from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine
from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine

router = APIRouter()


@router.get("/momentum-reversal-strategy")
def momentum_reversal_strategy(top_n: int = 5):
    """The rebuilt validated strategy's current target positions (dry run, no trades)."""
    return MomentumReversalStrategyEngine(top_n=top_n).run()


@router.get("/momentum-reversal-rebalance")
def momentum_reversal_rebalance(force: bool = False, top_n: int = 5):
    """Rebalance status; ?force=true realizes prior holdings and opens the current top-N now."""
    eng = MomentumReversalRebalanceEngine(top_n=top_n)
    return eng.rebalance(force=True) if force else eng.status()
