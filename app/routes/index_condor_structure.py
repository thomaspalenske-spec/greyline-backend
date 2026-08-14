from fastapi import APIRouter

from app.services.index_condor_structure_backtest_engine import IndexCondorStructureBacktestEngine

router = APIRouter()


@router.get("/index-condor-structure-backtest")
def index_condor_structure_backtest(rerun: bool = False):
    """The confirmed index VRP as a tradeable DEFINED-RISK iron condor over 2003-2026 (VIX-priced legs,
    real SPY crash paths). Shows the defined-risk vs naked comparison (wings cap the tail), ROR by year
    (2008/2020 visible), Sharpe + tail. MODELED — see caveats; robust readouts are the tail-cap + crash
    survival, not the Sharpe level. rerun=true recomputes (fast, on-disk VIX+SPY)."""
    eng = IndexCondorStructureBacktestEngine()
    return eng.run() if rerun else (eng.last_study() if eng.last_study().get("status") != "NO_STUDY_YET" else eng.run())
