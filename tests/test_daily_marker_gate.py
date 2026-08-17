"""Daily once/UTC-day marker used to gate the tradability scan + survivorship snapshot off the
per-cycle hot path. Fail-open (never silently skips integrity work) + stamp-after-success (a
transient failure still retries next cycle).
"""
from app.services.background_scheduler_service import BackgroundSchedulerService as B


def test_due_when_no_marker(tmp_path):
    m = str(tmp_path / ".mk")
    assert B._day_marker_due(m) is True


def test_not_due_after_stamp(tmp_path):
    m = str(tmp_path / ".mk")
    assert B._day_marker_due(m) is True
    B._day_marker_stamp(m)
    assert B._day_marker_due(m) is False


def test_fail_open_on_unreadable_marker(tmp_path):
    # a directory where the file is expected -> read raises -> must fail OPEN (True = run the task),
    # never fail closed (which would silently skip a survivorship snapshot = permanent data loss)
    d = tmp_path / "marker_is_a_dir"
    d.mkdir()
    assert B._day_marker_due(str(d)) is True


def test_stamp_is_bulletproof(tmp_path):
    m = str(tmp_path / "sub" / ".mk")   # parent dir does not exist yet -> stamp must create it, not raise
    B._day_marker_stamp(m)
    assert B._day_marker_due(m) is False
