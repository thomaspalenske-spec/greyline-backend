"""Cycle-failure forensics: classification, signed distance-to-open, persistence/aggregation, and the
open-critical prompt-retry interval. No network, no orders."""

from datetime import datetime
from pathlib import Path

import pytest

from app.services.cycle_failure_forensics_engine import CycleFailureForensicsEngine as CF
from app.services.background_scheduler_service import BackgroundSchedulerService as SCHED


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(CF, "LOG", tmp_path / "cycle_failures.jsonl")
    return CF.LOG


# ---- classification: a small, stable, actionable bucket set ----

@pytest.mark.parametrize("err,expect", [
    ("HTTP 429 from unusualwhales rate limit", "UW_RATE_LIMIT"),
    ("token refresh failed: invalid_grant", "TS_AUTH"),
    ("brokerage/accounts order place rejected", "TS_ORDER"),
    ("tradestation marketdata quote barchart empty", "TS_QUOTE"),
    ("positions read degraded — fail-closed", "BROKER_READ"),
    ("requests.exceptions.ReadTimeout: timed out", "TIMEOUT"),
    ("ConnectionError: Max retries exceeded (SSL)", "NETWORK"),
    ("KeyError: 'symbol' NoneType has no attribute", "CODE_BUG"),
    ("something totally unmapped happened", "OTHER"),
    ("", "UNKNOWN"),
    (None, "UNKNOWN"),
])
def test_classify(err, expect):
    assert CF.classify(err) == expect


# ---- signed minutes-to-open ----

def test_minutes_to_open_premarket_negative():
    now = datetime(2026, 8, 17, 9, 25)                 # Monday, 5 min BEFORE the 09:30 open
    assert CF._minutes_to_open(now, {"is_weekday": True, "is_holiday": False}) == -5.0

def test_minutes_to_open_after_open_positive():
    now = datetime(2026, 8, 17, 9, 50)                 # 20 min AFTER
    assert CF._minutes_to_open(now, {"is_weekday": True, "is_holiday": False}) == 20.0

def test_minutes_to_open_none_on_weekend_or_holiday():
    now = datetime(2026, 8, 17, 9, 25)
    assert CF._minutes_to_open(now, {"is_weekday": False, "is_holiday": False}) is None
    assert CF._minutes_to_open(now, {"is_weekday": True, "is_holiday": True}) is None
    assert CF._minutes_to_open(None, {"is_weekday": True, "is_holiday": False}) is None


# ---- record + near_open flag + persistence ----

def test_record_marks_near_open(tmp_log, monkeypatch):
    # 3 min before the open on a trading day -> near_open True
    monkeypatch.setattr(CF, "_now_et", classmethod(
        lambda cls: (datetime(2026, 8, 17, 9, 27), {"is_weekday": True, "is_holiday": False,
                                                     "state": "MARKET_CLOSED_PREMARKET"})))
    rec = CF.record("brokerage/accounts positions read degraded", phase_hint="pre_sleeve")
    assert rec["near_open"] is True
    assert rec["error_class"] == "BROKER_READ"
    assert rec["phase_after"] == "pre_sleeve"
    assert -20 <= rec["minutes_to_open"] <= 20
    assert Path(tmp_log).exists()

def test_record_far_from_open_not_near(tmp_log, monkeypatch):
    monkeypatch.setattr(CF, "_now_et", classmethod(
        lambda cls: (datetime(2026, 8, 17, 13, 0), {"is_weekday": True, "is_holiday": False,
                                                    "state": "MARKET_OPEN_REGULAR_SESSION"})))
    rec = CF.record("ReadTimeout", phase_hint="institutional")
    assert rec["near_open"] is False
    assert rec["error_class"] == "TIMEOUT"


def test_summary_aggregates_and_counts_near_open(tmp_log, monkeypatch):
    # two near-open TS failures + one midday timeout
    monkeypatch.setattr(CF, "_now_et", classmethod(
        lambda cls: (datetime(2026, 8, 17, 9, 31), {"is_weekday": True, "is_holiday": False,
                                                    "state": "MARKET_OPEN_REGULAR_SESSION"})))
    CF.record("tradestation quote failed")
    CF.record("brokerage/accounts order rejected")
    monkeypatch.setattr(CF, "_now_et", classmethod(
        lambda cls: (datetime(2026, 8, 17, 12, 0), {"is_weekday": True, "is_holiday": False,
                                                    "state": "MARKET_OPEN_REGULAR_SESSION"})))
    CF.record("ReadTimeout")
    s = CF.summary()
    assert s["recorded"] == 3
    assert s["near_open_failures"] == 2
    classes = {c["class"]: c["count"] for c in s["by_class"]}
    assert classes.get("TS_QUOTE") == 1 and classes.get("TS_ORDER") == 1 and classes.get("TIMEOUT") == 1


def test_summary_empty_is_clean(tmp_log):
    s = CF.summary()
    assert s["recorded"] == 0 and s["near_open_failures"] == 0 and s["by_class"] == []


def test_phase_hint_picks_last_real_phase():
    assert CF._phase_hint_from_timings({"pre_sleeve": 1.0, "sleeves": 2.0, "_total_instrumented": 3.0}) == "sleeves"
    assert CF._phase_hint_from_timings({}) is None
    assert CF._phase_hint_from_timings(None) is None


# ---- open-critical prompt-retry interval ----

def _patch_mins(monkeypatch, mins):
    monkeypatch.setattr(CF, "_now_et", classmethod(lambda cls: (datetime(2026, 8, 17, 9, 30), {})))
    monkeypatch.setattr(CF, "_minutes_to_open", classmethod(lambda cls, a, b: mins))

def test_next_interval_full_when_not_failed(monkeypatch):
    _patch_mins(monkeypatch, 2.0)
    assert SCHED._next_interval(300, failed=False) == 300

def test_next_interval_short_backoff_on_near_open_failure(monkeypatch):
    monkeypatch.setenv("GREYLINE_OPEN_RETRY_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_OPEN_RETRY_BACKOFF_SEC", "45")
    _patch_mins(monkeypatch, 3.0)                      # within ±20 min of the open
    assert SCHED._next_interval(300, failed=True) == 45

def test_next_interval_full_when_failure_far_from_open(monkeypatch):
    monkeypatch.setenv("GREYLINE_OPEN_RETRY_ENABLED", "true")
    _patch_mins(monkeypatch, 200.0)                    # midday
    assert SCHED._next_interval(300, failed=True) == 300

def test_next_interval_respects_gate_off(monkeypatch):
    monkeypatch.setenv("GREYLINE_OPEN_RETRY_ENABLED", "false")
    _patch_mins(monkeypatch, 1.0)
    assert SCHED._next_interval(300, failed=True) == 300

def test_next_interval_never_longer_than_normal(monkeypatch):
    monkeypatch.setenv("GREYLINE_OPEN_RETRY_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_OPEN_RETRY_BACKOFF_SEC", "45")
    _patch_mins(monkeypatch, 1.0)
    assert SCHED._next_interval(30, failed=True) == 30   # backoff capped at the (smaller) normal interval
