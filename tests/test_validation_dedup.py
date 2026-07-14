import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.validation_dedup import dedupe_by_symbol_time


def test_collapses_same_symbol_same_minute():
    entries = [
        {"symbol": "MSTR", "timestamp": "2026-07-13T11:18:55.100", "flow_direction": "BULLISH"},
        {"symbol": "MSTR", "timestamp": "2026-07-13T11:18:55.900", "flow_direction": "BULLISH"},
        {"symbol": "MSTR", "timestamp": "2026-07-13T11:18:22.000", "flow_direction": "BULLISH"},
        {"symbol": "MSTR", "timestamp": "2026-07-13T11:25:00.000", "flow_direction": "BEARISH"},  # diff minute
        {"symbol": "AMD", "timestamp": "2026-07-13T11:18:00.000", "flow_direction": "BULLISH"},   # diff symbol
    ]
    out = dedupe_by_symbol_time(entries)
    # MSTR@11:18 (1), MSTR@11:25 (1), AMD@11:18 (1) = 3 independent observations
    assert len(out) == 3


def test_keeps_last_in_bucket():
    entries = [
        {"symbol": "X", "timestamp": "2026-07-13T11:18:01", "v": 1},
        {"symbol": "X", "timestamp": "2026-07-13T11:18:59", "v": 2},
    ]
    out = dedupe_by_symbol_time(entries)
    assert len(out) == 1 and out[0]["v"] == 2


def test_hour_bucket_stricter():
    entries = [
        {"symbol": "X", "timestamp": "2026-07-13T11:05"},
        {"symbol": "X", "timestamp": "2026-07-13T11:55"},
    ]
    assert len(dedupe_by_symbol_time(entries, bucket_chars=13)) == 1  # same hour


def test_case_insensitive_symbol():
    entries = [
        {"symbol": "spy", "timestamp": "2026-07-13T11:18:01"},
        {"symbol": "SPY", "timestamp": "2026-07-13T11:18:02"},
    ]
    assert len(dedupe_by_symbol_time(entries)) == 1
