from fastapi import APIRouter

from app.services.edge_first_close_watch_engine import EdgeFirstCloseWatchEngine

router = APIRouter()


@router.get("/edge-first-close")
def edge_first_close():
    """Which sleeves have booked their first NON-FORCED (strategy-logic) close — the milestone that
    starts real edge accumulation. Read-only; never pages."""
    return EdgeFirstCloseWatchEngine().status()
