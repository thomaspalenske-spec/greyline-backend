from fastapi import APIRouter

from app.services.momentum_reversal_backtest_engine import MomentumReversalBacktestEngine

router = APIRouter()


@router.get("/momentum-reversal-backtest")
def momentum_reversal_backtest(verdict: bool = True, long_only: bool = False):
    """Cost-aware out-of-sample backtest of GreyLine's momentum-reversal signal (EQUITY /
    total-return; no historical option data exists so the options call is analytical).
    Default returns the full verdict (edge + beta decomposition + options-vehicle call)."""
    eng = MomentumReversalBacktestEngine()
    return eng.verdict() if verdict else eng.run(long_only=long_only)
