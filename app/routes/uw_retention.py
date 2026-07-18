from fastapi import APIRouter

from app.services.uw_snapshot_retention_engine import UWSnapshotRetentionEngine

router = APIRouter()


@router.get("/uw-retention")
def uw_retention(run: bool = False):
    """UW snapshot retention. Default is a dry run (what would be reclaimed); ?run=true prunes now."""
    eng = UWSnapshotRetentionEngine()
    return eng.prune(force=True) if run else eng.prune(dry_run=True)
