"""Lineage detection must catch a SILENT change to settled history — and must NOT false-alarm
on the legitimate daily append. The whole value is reproducibility: a changed past bar can
never be invisible."""

import csv
from datetime import datetime

import pytest

from app.services.price_bar_lineage_engine import PriceBarLineageEngine

HDR = "date,open,high,low,close,volume\n"


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(PriceBarLineageEngine, "HIST_DIR", tmp_path)
    monkeypatch.setattr(PriceBarLineageEngine, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(PriceBarLineageEngine, "REPORT", tmp_path / "report.json")
    return PriceBarLineageEngine()


def _write(tmp_path, sym, rows):
    (tmp_path / f"{sym}_daily.csv").write_text(HDR + "".join(rows))


def _settled_history(sym_close=100.0):
    # dates well before the 5-day settled cutoff -> all settled
    return [f"20{y:02d}-06-15,{sym_close},{sym_close+1},{sym_close-1},{sym_close},1000000\n"
            for y in range(10, 24)]   # 2010..2023, one bar per year


def test_unchanged_history_is_stable(eng, tmp_path):
    _write(tmp_path, "AAA", _settled_history())
    eng.snapshot()
    r = eng.verify()
    assert r["status"] == "LINEAGE_STABLE" and r["changed_count"] == 0


def test_a_silently_altered_settled_bar_is_caught(eng, tmp_path):
    """THE guarantee. A 2019 bar changes value -> detected, localized to 2019, flagged as a
    targeted restatement/corruption (not a re-adjustment)."""
    rows = _settled_history()
    _write(tmp_path, "AAA", rows)
    eng.snapshot()
    # rewrite the 2019 bar's close 100 -> 137 (one year only)
    rows[9] = "2019-06-15,137,138,136,137,1000000\n"
    _write(tmp_path, "AAA", rows)
    r = eng.verify()
    assert r["status"] == "SETTLED_HISTORY_CHANGED_SINCE_BASELINE"
    ch = r["changed"][0]
    assert ch["symbol"] == "AAA"
    assert ch["years_changed"] == ["2019"]
    assert ch["likely"] == "TARGETED_RESTATEMENT_OR_CORRUPTION"


def test_a_retroactive_readjustment_is_classified_as_such(eng, tmp_path):
    """A split re-adjusts EVERY historical bar. That must be caught AND recognised as a
    re-adjustment (spans most years), not mistaken for single-bar corruption."""
    _write(tmp_path, "AAA", _settled_history(100.0))
    eng.snapshot()
    # 2:1 split re-adjustment: every historical bar's prices halve
    halved = [f"20{y:02d}-06-15,50.0,50.5,49.5,50.0,1000000\n" for y in range(10, 24)]
    _write(tmp_path, "AAA", halved)
    ch = eng.verify()["changed"][0]
    assert ch["likely"] == "RETROACTIVE_READJUSTMENT"
    assert ch["years_changed_count"] >= 2


def test_appending_a_new_recent_bar_does_not_false_alarm(eng, tmp_path):
    """The legitimate daily append (a bar AFTER the settled cutoff) must never be flagged —
    otherwise the operator learns to ignore the alarm."""
    rows = _settled_history()
    _write(tmp_path, "AAA", rows)
    eng.snapshot()
    today = datetime.utcnow().date().isoformat()          # dynamic — always past the 5-day settled cutoff
    rows.append(f"{today},200,201,199,200,1000000\n")      # a fresh unsettled bar (legit daily append)
    _write(tmp_path, "AAA", rows)
    assert eng.verify()["status"] == "LINEAGE_STABLE"


def test_a_new_symbol_is_reported_as_new_not_corruption(eng, tmp_path):
    _write(tmp_path, "AAA", _settled_history())
    eng.snapshot()
    _write(tmp_path, "BBB", _settled_history(50.0))
    r = eng.verify()
    assert r["status"] == "LINEAGE_STABLE"          # a new file is not a CHANGE to old data
    assert "BBB" in r["new_symbols"]


def test_a_removed_symbol_is_reported(eng, tmp_path):
    _write(tmp_path, "AAA", _settled_history())
    _write(tmp_path, "BBB", _settled_history(50.0))
    eng.snapshot()
    (tmp_path / "BBB_daily.csv").unlink()
    r = eng.verify()
    assert any(x["symbol"] == "BBB" for x in r["removed"])


def test_reaccepting_the_baseline_clears_a_known_change(eng, tmp_path):
    """After review, an operator re-accepts. Only an explicit force does it — a change is
    never silently absorbed."""
    rows = _settled_history()
    _write(tmp_path, "AAA", rows)
    eng.snapshot()
    rows[9] = "2019-06-15,137,138,136,137,1000000\n"
    _write(tmp_path, "AAA", rows)
    assert eng.verify()["changed_count"] == 1
    assert eng.snapshot()["created"] is False        # won't silently re-baseline
    eng.snapshot(force=True)                          # explicit acceptance
    assert eng.verify()["status"] == "LINEAGE_STABLE"
