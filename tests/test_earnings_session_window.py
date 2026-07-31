"""The earnings feed gates on TRADING SESSIONS to the report, not calendar days — so a Monday reporter
is caught from the prior Friday (its last pre-report session) instead of silently slipping the window.

No network — the panel is a tmp file.
"""

import json
from datetime import date

from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine


def _sessions(today, report):
    return EarningsVolHarvestEngine._sessions_to(date.fromisoformat(today), date.fromisoformat(report))


def test_session_counting_is_weekend_aware():
    assert _sessions("2026-08-07", "2026-08-10") == 1     # Fri -> Mon report = 1 session away (the gap)
    assert _sessions("2026-08-05", "2026-08-06") == 1     # Wed -> Thu = 1
    assert _sessions("2026-08-04", "2026-08-06") == 2     # Tue -> Thu = 2
    assert _sessions("2026-08-03", "2026-08-06") == 3     # Mon -> Thu = 3 (too early, excluded)
    assert _sessions("2026-08-06", "2026-08-06") == 0     # report day itself = 0 (excluded)


def _panel(tmp_path, rows):
    p = tmp_path / "panel.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def test_monday_reporter_is_caught_from_friday(tmp_path, monkeypatch):
    eng = EarningsVolHarvestEngine()
    # Name reports Monday 2026-08-10; evaluated on the prior Friday 2026-08-07.
    eng.PANEL = _panel(tmp_path, [
        {"kind": "implied", "ticker": "MONCO", "report_date": "2026-08-10", "iv_rank": 85, "implied_move_pct": 9.0}])
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    cands = [c["ticker"] for c in eng._candidates(today=date(2026, 8, 7))]
    assert cands == ["MONCO"]                             # previously missed (Fri->Mon = 3 calendar days)


def test_too_early_is_still_excluded(tmp_path, monkeypatch):
    eng = EarningsVolHarvestEngine()
    eng.PANEL = _panel(tmp_path, [
        {"kind": "implied", "ticker": "FARCO", "report_date": "2026-08-13", "iv_rank": 90, "implied_move_pct": 9.0}])
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    # Monday 2026-08-10 -> Thursday 2026-08-13 is 3 sessions: outside the 1-2 window.
    assert eng._candidates(today=date(2026, 8, 10)) == []
