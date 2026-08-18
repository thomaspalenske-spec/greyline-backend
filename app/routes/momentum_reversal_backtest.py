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


@router.get("/total-return-signal-impact")
def total_return_signal_impact():
    """Measures the cost of the live signal reading PRICE-ONLY closes while the backtest reads dividend-
    adjusted adj_close: the factor A/B (adjusted vs price-only) plus how many signals flip and how many of
    those flips sit on an ex-dividend/distribution day (the false reversals adjustment removes). The
    evidence for flipping GREYLINE_MOMENTUM_TOTAL_RETURN on."""
    from app.services.total_return_signal_impact_engine import TotalReturnSignalImpactEngine
    return TotalReturnSignalImpactEngine().run()
