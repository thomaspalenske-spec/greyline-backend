import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.continuity_monitor_engine import ContinuityMonitorEngine

T0 = datetime(2026, 7, 14, 14, 0, 0)


def _hb(tmp_path, times):
    p = tmp_path / "heartbeat.jsonl"
    p.write_text("".join(json.dumps({"at": t.isoformat(), "status": "COMPLETE"}) + "\n" for t in times))
    eng = ContinuityMonitorEngine()
    eng.HEARTBEAT = p
    return eng


def _steady(n, minutes=3, start=T0):
    return [start + timedelta(minutes=minutes * i) for i in range(n)]


def test_continuous_stream_is_green(tmp_path):
    times = _steady(30)
    eng = _hb(tmp_path, times)
    out = eng.diagnose(now=times[-1] + timedelta(minutes=2))

    assert out["verdict"] == "GREEN"
    assert out["gap_count"] == 0


def test_detects_a_gap_and_reports_it(tmp_path):
    # 20 steady beats, then a 90-min hole (a laptop sleep), then it resumes.
    first = _steady(20)
    resume_start = first[-1] + timedelta(minutes=90)
    second = _steady(14, start=resume_start)[1:]
    eng = _hb(tmp_path, first + second)

    out = eng.diagnose(now=(first + second)[-1] + timedelta(minutes=2))
    assert out["verdict"] == "AMBER"
    assert out["gap_count"] == 1
    assert out["largest_gap_minutes"] >= 90
    assert out["recent_gaps"][0]["minutes"] >= 90


def test_stale_heartbeat_is_red_and_not_live(tmp_path):
    # System stopped: last beat is hours old relative to "now".
    times = _steady(20)
    eng = _hb(tmp_path, times)

    out = eng.diagnose(now=times[-1] + timedelta(hours=2))
    assert out["verdict"] == "RED"
    assert out["currently_live"] is False


def test_self_calibrates_to_actual_cadence(tmp_path):
    # A slow 30-min cadence should NOT flag every normal interval as a gap.
    times = _steady(20, minutes=30)
    eng = _hb(tmp_path, times)

    out = eng.diagnose(now=times[-1] + timedelta(minutes=20))
    assert out["gap_count"] == 0
    assert out["median_cadence_minutes"] == 30.0


def test_warming_up_with_too_few_beats(tmp_path):
    eng = _hb(tmp_path, _steady(1))
    out = eng.diagnose()
    assert out["verdict"] == "UNKNOWN"
