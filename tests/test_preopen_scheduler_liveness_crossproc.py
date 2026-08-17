"""The pre-open readiness audit must not cry wolf on scheduler_liveness when run OUTSIDE the service
process (thread_alive is process-local). It should confirm liveness via the scheduler's own persisted
cycle history instead — a recent COMPLETE cycle = alive, regardless of which process audits.
"""
import json
from datetime import datetime, timedelta

from app.services.pre_open_readiness_engine import PreOpenReadinessEngine as P


def _write_cycle(tmp_path, minutes_ago, status="BACKGROUND_SCHEDULER_CYCLE_COMPLETE"):
    f = tmp_path / "cycle_cost_history.jsonl"
    ts = (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat()
    f.write_text(json.dumps({"timestamp": ts, "status": status, "cycle_seconds": 120}) + "\n")
    return f


def test_recent_cycle_reads_alive(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CYCLE_COST_HISTORY", _write_cycle(tmp_path, 6))
    alive, detail = P._scheduler_alive_cross_process()
    assert alive is True and "min ago" in detail


def test_stale_cycle_reads_not_alive(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CYCLE_COST_HISTORY", _write_cycle(tmp_path, 60))   # > 20min freshness window
    assert P._scheduler_alive_cross_process()[0] is False


def test_missing_history_not_alive(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CYCLE_COST_HISTORY", tmp_path / "nope.jsonl")
    alive, detail = P._scheduler_alive_cross_process()
    assert alive is False and "no persisted cycle history" in detail


def test_incomplete_cycle_not_alive(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "CYCLE_COST_HISTORY", _write_cycle(tmp_path, 2, status="DEGRADED"))
    assert P._scheduler_alive_cross_process()[0] is False   # recent but not COMPLETE
