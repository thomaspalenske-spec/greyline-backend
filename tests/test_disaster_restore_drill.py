"""Restore drill: proves the off-machine backup is RESTORABLE (present + non-empty + parses), not just
written. No network — the remote fetch is mocked. No real alerts — dispatch is mocked.
"""

import json

import app.services.external_alert_engine as eae
from app.services.disaster_restore_drill_engine import DisasterRestoreDrillEngine as D


EXPECTED = ["a/ledger.jsonl", "b/panel.json", "c/bars.csv"]


def _good_tree():
    return {
        "a/ledger.jsonl": (json.dumps({"x": 1}) + "\n" + json.dumps({"x": 2}) + "\n").encode(),
        "b/panel.json": json.dumps({"ok": True}).encode(),
        "c/bars.csv": b"date,close\n2026-08-05,100.0\n",
    }


def test_verify_complete_tree_is_restorable():
    r = D()._verify(_good_tree(), EXPECTED)
    assert r["restorable"] is True and r["status"] == "RESTORE_DRILL_VERIFIED"
    assert r["verified"] == 3 and r["missing"] == [] and r["corrupt"] == []


def test_verify_missing_file_fails():
    tree = _good_tree()
    del tree["b/panel.json"]
    r = D()._verify(tree, EXPECTED)
    assert r["restorable"] is False and r["status"] == "RESTORE_DRILL_FAILED"
    assert "b/panel.json" in r["missing"]


def test_verify_corrupt_json_fails():
    tree = _good_tree()
    tree["b/panel.json"] = b"{not valid json"
    r = D()._verify(tree, EXPECTED)
    assert r["restorable"] is False
    assert any(c["file"] == "b/panel.json" for c in r["corrupt"])


def test_empty_jsonl_is_legitimately_restorable():
    """An empty ledger (0 trades) is a VALID state, not corruption — the backup faithfully restores it.
    Regression for the false-positive the live drill caught on options_paper_trade_ledger.jsonl."""
    tree = _good_tree()
    tree["a/ledger.jsonl"] = b""
    r = D()._verify(tree, EXPECTED)
    assert r["restorable"] is True and r["verified"] == 3


def test_empty_json_object_file_fails():
    """An empty .json IS invalid (can't parse as a JSON object) — that's real corruption."""
    tree = _good_tree()
    tree["b/panel.json"] = b""
    r = D()._verify(tree, EXPECTED)
    assert r["restorable"] is False
    assert any(c["file"] == "b/panel.json" for c in r["corrupt"])


def test_drill_fetch_failure_is_reported_not_silent(monkeypatch):
    monkeypatch.setattr(D, "_expected_rel_paths", lambda self: EXPECTED)
    monkeypatch.setattr(D, "_fetch_backup_tree", lambda self: None)     # remote unreachable
    r = D().drill()
    assert r["restorable"] is False and r["status"] == "RESTORE_DRILL_FETCH_FAILED"


def test_run_if_due_pages_critical_on_failed_restore(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "MARKER", tmp_path / "restore_drill_last.json")
    monkeypatch.setattr(D, "_expected_rel_paths", lambda self: EXPECTED)
    tree = _good_tree(); del tree["c/bars.csv"]                          # a file missing -> not restorable
    monkeypatch.setattr(D, "_fetch_backup_tree", lambda self: tree)
    calls = []
    monkeypatch.setattr(eae.ExternalAlertEngine, "dispatch",
                        lambda self, title, message, **k: calls.append((title, k.get("severity"))) or {"status": "X"})
    r = D().run_if_due()                                                # never run -> due
    assert r["status"] == "RESTORE_DRILL_FAILED"
    assert len(calls) == 1 and calls[0][1] == "CRITICAL"
    # marker written so the next run is gated and the reality guard can read it
    assert (tmp_path / "restore_drill_last.json").exists()


def test_run_if_due_is_gated_after_a_recent_run(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "MARKER", tmp_path / "restore_drill_last.json")
    monkeypatch.setattr(D, "_expected_rel_paths", lambda self: EXPECTED)
    monkeypatch.setattr(D, "_fetch_backup_tree", lambda self: _good_tree())
    calls = []
    monkeypatch.setattr(eae.ExternalAlertEngine, "dispatch", lambda self, *a, **k: calls.append(1) or {})
    r1 = D().run_if_due()
    assert r1["status"] == "RESTORE_DRILL_VERIFIED"
    r2 = D().run_if_due()                                               # within DUE_HOURS -> gated
    assert r2["status"] == "RESTORE_DRILL_NOT_DUE"
    assert calls == []                                                  # verified restore never pages
