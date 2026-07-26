from fastapi import APIRouter

from app.services.portfolio_greeks_engine import PortfolioGreeksEngine

router = APIRouter()


@router.get("/portfolio-greeks")
def portfolio_greeks():
    """The book's aggregate greeks (net delta/vega/gamma/theta) and the delta-neutral hedge — the
    difference between selling options and running a vol book."""
    return PortfolioGreeksEngine().book_greeks()


@router.post("/portfolio-greeks/hedge")
def portfolio_greeks_hedge(dry_run: bool = True):
    """Trade the underlying to bring the book delta-neutral (GATED: real order only when
    GREYLINE_GREEKS_DELTA_HEDGE=true and dry_run=false)."""
    return PortfolioGreeksEngine().hedge_delta(dry_run=dry_run)
