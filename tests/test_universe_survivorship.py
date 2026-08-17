"""Survivorship: the past can't be fixed, so the forward record must never be lost."""

import json
from datetime import datetime, timedelta

import pytest

from app.services.universe_survivorship_engine import UniverseSurvivorshipEngine

HDR = "date,open,high,low,close,volume\n"

# An "alive" symbol's last bar must be recent RELATIVE TO TODAY (inside STALE_DAYS), or the test rots:
# a hardcoded date silently crosses the staleness cutoff as wall-clock time advances and the live name
# gets flagged as departed. Computed each run so it stays inside the window.
RECENT = (datetime.utcnow().date() - timedelta(days=1)).isoformat()


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(UniverseSurvivorshipEngine, "HIST_DIR", tmp_path)
    monkeypatch.setattr(UniverseSurvivorshipEngine, "ARCHIVE", tmp_path / "pit.jsonl")
    monkeypatch.setattr(UniverseSurvivorshipEngine, "DELISTED", tmp_path / "delisted.json")
    return UniverseSurvivorshipEngine()


def _sym(tmp_path, name, last_date):
    (tmp_path / f"{name}_daily.csv").write_text(
        HDR + f"2026-01-02,10,11,9,10,1000000\n{last_date},10,11,9,10,1000000\n")


def test_membership_on_an_unarchived_date_returns_none_not_todays_list(eng, tmp_path):
    """THE anti-bias guarantee. Silently substituting today's membership for a date we never
    recorded IS survivorship bias — the exact mistake that erased SIVB and FRC."""
    _sym(tmp_path, "AAA", "2026-07-20")
    eng.snapshot()
    assert eng.membership_on("2020-01-01") is None      # predates the archive -> admit it


def test_a_departing_symbol_is_retained_not_deleted(eng, tmp_path):
    """A delisting is the observation a survivorship-free dataset is MADE of. TradeStation
    returns 'Invalid Symbol' for dead tickers, so a file discarded now is gone forever."""
    _sym(tmp_path, "ALIVE", RECENT)                     # last bar yesterday -> inside STALE_DAYS, alive
    _sym(tmp_path, "DEAD", "2026-01-05")                # feed went quiet long ago
    out = eng.detect_departures()
    assert out["newly_recorded"] == ["DEAD"]
    assert (tmp_path / "DEAD_daily.csv").exists()       # never deleted
    reg = json.loads((tmp_path / "delisted.json").read_text())
    assert reg["DEAD"]["last_bar_date"] == "2026-01-05"


def test_departures_are_recorded_once_not_re_flagged(eng, tmp_path):
    _sym(tmp_path, "DEAD", "2026-01-05")
    assert eng.detect_departures()["newly_recorded"] == ["DEAD"]
    assert eng.detect_departures()["newly_recorded"] == []       # idempotent


def test_snapshot_is_once_per_day_and_tracks_membership_change(eng, tmp_path):
    _sym(tmp_path, "AAA", "2026-07-20")
    first = eng.snapshot()
    assert first["status"] == "PIT_SNAPSHOT_RECORDED"
    again = eng.snapshot()
    assert again["status"] == "PIT_SNAPSHOT_ALREADY_TAKEN_TODAY"   # no duplicate days
    assert again["archive_days"] == 1


def test_status_never_claims_history_is_survivorship_free(eng, tmp_path):
    """Overstating this is worse than the bias: it would let a future 'edge' pass unchallenged."""
    _sym(tmp_path, "AAA", "2026-07-20")
    eng.snapshot()
    st = eng.status()
    assert st["history_is_survivorship_biased"] is True
    assert st["survivorship_free_from"] is not None
    assert "biased upward" in st["detail"].lower()
