from app.services.paper_snapshot_scheduler_engine import (
    PaperSnapshotSchedulerEngine
)


def endpoint():
    return PaperSnapshotSchedulerEngine().run_cycle(
        cash_balance=10000.0,
        positions=[]
    )
