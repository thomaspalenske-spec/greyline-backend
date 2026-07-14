import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.background_scheduler_service import BackgroundSchedulerService
from app.services.ops_metrics_engine import OpsMetricsEngine

OPS = "app.services.ops_metrics_engine"


# ---- scheduler cycle observability ----
def _reset_scheduler():
    BackgroundSchedulerService._success_count = 0
    BackgroundSchedulerService._failure_count = 0
    BackgroundSchedulerService._consecutive_failures = 0
    BackgroundSchedulerService._last_error = None
    BackgroundSchedulerService._recent_cycles = []


def test_record_result_tracks_success_and_failure():
    _reset_scheduler()
    started = "2026-07-12T00:00:00"
    BackgroundSchedulerService._record_result("COMPLETE", started)
    BackgroundSchedulerService._record_result("COMPLETE", started)
    BackgroundSchedulerService._record_result("FAILED", started, error="boom")

    assert BackgroundSchedulerService._success_count == 2
    assert BackgroundSchedulerService._failure_count == 1
    assert BackgroundSchedulerService._consecutive_failures == 1
    assert BackgroundSchedulerService._last_error == "boom"
    assert len(BackgroundSchedulerService._recent_cycles) == 3


def test_consecutive_failures_reset_on_success():
    _reset_scheduler()
    BackgroundSchedulerService._record_result("FAILED", "2026-07-12T00:00:00", error="e")
    BackgroundSchedulerService._record_result("FAILED", "2026-07-12T00:00:00", error="e")
    assert BackgroundSchedulerService._consecutive_failures == 2
    BackgroundSchedulerService._record_result("COMPLETE", "2026-07-12T00:00:00")
    assert BackgroundSchedulerService._consecutive_failures == 0


def test_recent_cycles_capped():
    _reset_scheduler()
    for _ in range(BackgroundSchedulerService._RECENT_CAP + 10):
        BackgroundSchedulerService._record_result("COMPLETE", "2026-07-12T00:00:00")
    assert len(BackgroundSchedulerService._recent_cycles) == BackgroundSchedulerService._RECENT_CAP


# ---- ops metrics roll-up ----
def _collect(scheduler, reliability_status="RELIABILITY_CORE_HEALTHY", store_ok=True):
    with patch(f"{OPS}.BackgroundSchedulerService") as MockSched, \
         patch(f"{OPS}.GreyLineReliabilityCoreEngine") as MockRel, \
         patch(f"{OPS}.ExecutionGovernor") as MockGov, \
         patch.object(OpsMetricsEngine, "_data_store_health", return_value=(store_ok, [] if store_ok else ["trade_ledger: boom"])):
        MockSched.status.return_value = scheduler
        MockRel.return_value.evaluate.return_value = {"status": reliability_status, "health_score": 100}
        MockGov.return_value.evaluate_execution_permission.return_value = {
            "execution_enabled": True, "order_placement_allowed": True, "execution_mode": "PAPER_ONLY",
        }
        return OpsMetricsEngine().collect()


def test_ops_green_when_all_healthy():
    r = _collect({"thread_alive": True, "consecutive_failures": 0, "cycle_count": 100})
    assert r["overall_status"] == "GREEN"
    assert r["problems"] == []


def test_ops_red_when_scheduler_thread_down():
    r = _collect({"thread_alive": False, "consecutive_failures": 0})
    assert r["overall_status"] == "RED"
    assert "SCHEDULER_THREAD_DOWN" in r["problems"]


def test_ops_red_when_data_store_degraded():
    r = _collect({"thread_alive": True, "consecutive_failures": 0}, store_ok=False)
    assert r["overall_status"] == "RED"
    assert "DATA_STORE_DEGRADED" in r["problems"]


def test_ops_yellow_on_a_few_consecutive_failures():
    r = _collect({"thread_alive": True, "consecutive_failures": 3})
    assert r["overall_status"] == "YELLOW"
    assert any("CONSECUTIVE_FAILURES" in p for p in r["problems"])


def test_ops_red_on_many_consecutive_failures():
    r = _collect({"thread_alive": True, "consecutive_failures": 5})
    assert r["overall_status"] == "RED"


def test_ops_yellow_when_reliability_degraded():
    r = _collect({"thread_alive": True, "consecutive_failures": 0}, reliability_status="RELIABILITY_CORE_DEGRADED")
    assert r["overall_status"] == "YELLOW"
    assert any("RELIABILITY" in p for p in r["problems"])
