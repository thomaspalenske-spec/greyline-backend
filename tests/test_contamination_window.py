"""Contamination-window registry + Edge Court exclusion + guard auto-population (2026-09-10)."""
import json
from pathlib import Path

from app.services.contamination_window_engine import ContaminationWindowEngine as C
from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


def test_registry_records_merges_and_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "FILE", tmp_path / "cw.json")
    assert C.record("low_vol", "2026-09-08T00:00:00", "2026-09-08T20:00:00", "churn")
    # a close inside the window for that sleeve is contaminated; another sleeve is not
    assert C.is_contaminated("low_vol", "2026-09-08T13:00:00") is True
    assert C.is_contaminated("trend", "2026-09-08T13:00:00") is False
    # a close outside the window is clean
    assert C.is_contaminated("low_vol", "2026-09-09T13:00:00") is False
    # firing again with an adjacent window EXTENDS (merges) rather than appends a second window
    C.record("low_vol", "2026-09-08T20:00:00", "2026-09-09T04:00:00", "churn")
    assert len(C.windows()) == 1
    assert C.is_contaminated("low_vol", "2026-09-09T03:00:00") is True


def test_star_sleeve_matches_all(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "FILE", tmp_path / "cw.json")
    C.record("*", "2026-09-08T00:00:00", "2026-09-08T23:59:59", "book-wide")
    assert C.is_contaminated("anything", "2026-09-08T12:00:00") is True


def test_missing_file_is_no_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "FILE", tmp_path / "nope.json")
    assert C.windows() == []
    assert C.is_contaminated("low_vol", "2026-09-08T12:00:00") is False


def test_churn_check_emits_structured_windows(tmp_path, monkeypatch):
    # a churned sleeve should expose churn_windows the scheduler can record
    import json as j
    p = tmp_path / "order_intent.jsonl"
    from datetime import datetime, timedelta
    def iso(m): return (datetime.utcnow() - timedelta(minutes=m)).isoformat()
    rows = []
    for i in range(4):
        rows.append({"ts": iso(30 + i), "strategy": "low_vol", "symbol": "XMLV", "action": "SELL", "qty": 5})
        rows.append({"ts": iso(20 + i), "strategy": "low_vol", "symbol": "XMLV", "action": "BUY", "qty": 5})
    p.write_text("\n".join(j.dumps(r) for r in rows))
    monkeypatch.setattr(G, "ORDER_INTENT_PATH", str(p))
    r = G()._check_sleeve_churn()
    assert r["ok"] is False
    assert any(w["sleeve"] == "low_vol" for w in r.get("churn_windows", []))
