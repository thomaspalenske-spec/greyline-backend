from fastapi import APIRouter

from app.services.index_variance_premium_panel_engine import IndexVariancePremiumPanelEngine

router = APIRouter()


@router.get("/index-variance-premium")
def index_variance_premium():
    """Out-of-sample scoreboard for THE candidate: the broad-index variance risk premium. Records
    the measured index harvest set daily, resolves ~30d out, reports a block-bootstrap CI once
    powered. The only test that can eventually include a real crash regime."""
    return IndexVariancePremiumPanelEngine().status()
