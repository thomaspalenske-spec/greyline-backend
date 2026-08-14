"""The institutional-flow pipeline (retrain + sweep) was ~59% of cycle cost yet is OBSERVATION_ONLY
and targets the unproven flow edge. It's now throttled to once/day, off-hours only. These pin that
gate so it can't silently regress back onto the per-cycle hot path.
"""
import pathlib

from app.services.background_scheduler_service import BackgroundSchedulerService as B

_OFF = {"market_time": "2026-08-14T20:00:00", "is_weekday": True, "is_holiday": False}   # 8pm ET
_OPEN = {"market_time": "2026-08-14T10:00:00", "is_weekday": True, "is_holiday": False}  # 10am ET


def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("GREYLINE_INSTITUTIONAL_PER_CYCLE", raising=False)
    B.INSTITUTIONAL_LAST_RUN = tmp_path / ".inst_last_run"


def test_deferred_during_open_window(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    due, reason = B._institutional_pipeline_due(_OPEN)
    assert due is False and "off-hours" in reason


def test_due_off_hours_when_not_yet_run(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    due, reason = B._institutional_pipeline_due(_OFF)
    assert due is True


def test_not_due_after_running_today(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert B._institutional_pipeline_due(_OFF)[0] is True
    B._stamp_institutional_run()
    due, reason = B._institutional_pipeline_due(_OFF)
    assert due is False and "already ran today" in reason


def test_per_cycle_override_forces_due_even_in_open_window(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("GREYLINE_INSTITUTIONAL_PER_CYCLE", "true")
    assert B._institutional_pipeline_due(_OPEN)[0] is True


def test_stamp_is_bulletproof(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    B._stamp_institutional_run()   # must not raise; must write today's date
    assert B.INSTITUTIONAL_LAST_RUN.exists()
