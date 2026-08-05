from fastapi import APIRouter

from app.services.sleeve_position_ledger_engine import SleevePositionLedgerEngine

router = APIRouter()


@router.get("/sleeve-positions")
def sleeve_positions():
    """Per-sleeve position ledger — which sleeve owns which shares. Lets overlapping sleeves run live
    without fighting over shared instruments (gated by GREYLINE_PER_SLEEVE_SIZING). Read-only."""
    return SleevePositionLedgerEngine.status()
