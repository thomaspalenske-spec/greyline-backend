from fastapi import APIRouter

from app.services.total_return_series_engine import TotalReturnSeriesEngine

router = APIRouter()


@router.get("/total-return-series")
def total_return_series(symbol: str = None, rebuild: bool = False):
    """Dividend+split adjusted total-return build report. ?symbol=MO rebuilds one name;
    ?rebuild=true rebuilds the whole universe (many UW calls)."""
    eng = TotalReturnSeriesEngine()
    if symbol:
        return eng.build_symbol(symbol.upper())
    if rebuild:
        return eng.build_universe()
    return eng.last_report() or {"status": "NO_TOTAL_RETURN_BUILD_YET",
                                 "detail": "?rebuild=true to build, or ?symbol=MO for one"}
