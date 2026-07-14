from datetime import datetime

from app.services.background_scheduler_service import BackgroundSchedulerService
from app.services.greyline_reliability_core_engine import GreyLineReliabilityCoreEngine
from app.services.execution_governor import ExecutionGovernor
from app.services.ledger_engine import LedgerEngine
from app.services.paper_account_snapshot_repository import PaperAccountSnapshotRepository

# Process start marker (resets on process restart / --reload; uptime is per-process).
_PROCESS_START = datetime.utcnow()


class OpsMetricsEngine:
    """
    Single consolidated operational health view: uptime, scheduler cycle health
    (success rate / consecutive failures / last error), reliability, execution
    state, and a live data-store integrity probe — rolled up into GREEN/YELLOW/RED.
    """

    def _data_store_health(self):
        errors = []
        checks = (
            ("trade_ledger", lambda: LedgerEngine().load()),
            ("paper_account_snapshots", lambda: PaperAccountSnapshotRepository().get_snapshots()),
        )
        for name, fn in checks:
            try:
                fn()
            except Exception as exc:
                errors.append(f"{name}: {exc!r}")
        return (len(errors) == 0), errors

    def collect(self):
        now = datetime.utcnow()
        uptime_seconds = round((now - _PROCESS_START).total_seconds(), 1)

        scheduler = BackgroundSchedulerService.status()
        alive = scheduler.get("thread_alive") is True
        consecutive = int(scheduler.get("consecutive_failures", 0) or 0)

        try:
            reliability = GreyLineReliabilityCoreEngine().evaluate()
            reliability_status = reliability.get("status")
            reliability_score = reliability.get("health_score")
        except Exception as exc:
            reliability_status = f"UNAVAILABLE: {exc!r}"
            reliability_score = None

        execution = ExecutionGovernor().evaluate_execution_permission("EXECUTE")
        store_ok, store_errors = self._data_store_health()

        problems = []
        if not alive:
            problems.append("SCHEDULER_THREAD_DOWN")
        if consecutive >= 3:
            problems.append(f"SCHEDULER_CONSECUTIVE_FAILURES_{consecutive}")
        if reliability_status != "RELIABILITY_CORE_HEALTHY":
            problems.append(f"RELIABILITY_{reliability_status}")
        if not store_ok:
            problems.append("DATA_STORE_DEGRADED")

        if (not alive) or (not store_ok) or (consecutive >= 5):
            overall = "RED"
        elif problems:
            overall = "YELLOW"
        else:
            overall = "GREEN"

        return {
            "timestamp": now.isoformat(),
            "system": "GreyLine",
            "overall_status": overall,
            "problems": problems,
            "uptime_seconds": uptime_seconds,
            "process_started_at": _PROCESS_START.isoformat(),
            "scheduler_health": {
                "thread_alive": alive,
                "cycle_count": scheduler.get("cycle_count"),
                "success_count": scheduler.get("success_count"),
                "failure_count": scheduler.get("failure_count"),
                "consecutive_failures": consecutive,
                "cycle_success_rate_pct": scheduler.get("cycle_success_rate_pct"),
                "last_status": scheduler.get("last_status"),
                "last_error": scheduler.get("last_error"),
                "last_error_at": scheduler.get("last_error_at"),
                "last_duration_ms": scheduler.get("last_duration_ms"),
            },
            "reliability": {
                "status": reliability_status,
                "health_score": reliability_score,
            },
            "execution": {
                "execution_enabled": execution.get("execution_enabled"),
                "order_placement_allowed": execution.get("order_placement_allowed"),
                "execution_mode": execution.get("execution_mode"),
            },
            "data_store": {
                "healthy": store_ok,
                "errors": store_errors,
            },
            "status": "OPS_METRICS_READY",
        }
