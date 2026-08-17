"""24-hour mission-book return. Honest None until ~24h of history exists; measured against the equity
~24h ago (not inception); appends throttled + pruned. Read-only, places no orders.
"""

import json
from datetime import datetime, timedelta

from app.services.account_return_horizon_engine import AccountReturnHorizonEngine as H


def _engine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return H()


def test_none_until_24h_of_history(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    out = e.record_and_measure(10000.0)             # first ever sample -> nothing ~24h old
    assert out["return_24h_pct"] is None
    assert "accumulating" in out["reason"]


def test_measures_against_equity_24h_ago(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    now = datetime(2026, 8, 17, 15, 0, 0)
    baseline_t = now - timedelta(hours=24)
    e.FILE.parent.mkdir(parents=True, exist_ok=True)
    e.FILE.write_text(json.dumps([{"t": baseline_t.isoformat(), "e": 10000.0}]))
    out = e.record_and_measure(10130.65, now=now)    # +1.3065% over the day
    assert out["return_24h_pct"] == 1.31
    assert out["baseline_equity"] == 10000.0


def test_ignores_baselines_outside_the_window(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    now = datetime(2026, 8, 17, 15, 0, 0)
    e.FILE.parent.mkdir(parents=True, exist_ok=True)
    # a 3h-old point (too recent) and a 48h-old point (too old, also pruned): neither is a 24h baseline
    e.FILE.write_text(json.dumps([
        {"t": (now - timedelta(hours=3)).isoformat(), "e": 9000.0},
        {"t": (now - timedelta(hours=48)).isoformat(), "e": 8000.0}]))
    out = e.record_and_measure(10000.0, now=now)
    assert out["return_24h_pct"] is None


def test_append_is_throttled(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    now = datetime(2026, 8, 17, 15, 0, 0)
    e.record_and_measure(10000.0, now=now)
    e.record_and_measure(10001.0, now=now + timedelta(minutes=1))   # < 5 min later -> not appended
    assert len(json.loads(e.FILE.read_text())) == 1
    e.record_and_measure(10002.0, now=now + timedelta(minutes=6))   # > 5 min -> appended
    assert len(json.loads(e.FILE.read_text())) == 2


def test_measure_only_does_not_record(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    out = e.measure_only(10000.0)
    assert out["return_24h_pct"] is None
    assert not e.FILE.exists()                        # degraded read must not write a sample
