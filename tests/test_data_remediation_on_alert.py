"""Event-driven remediation (run_on_alert): fix data faults the moment a validator flags them,
without hammering the TradeStation API. Fully mocked — no scan, no API, no orders."""

import json

import app.services.data_remediation_engine as dre_mod
from app.services.data_remediation_engine import DataRemediationEngine as D


def _eng(tmp_path, monkeypatch, signature):
    monkeypatch.setenv("GREYLINE_DATA_AUTOREMEDIATE", "true")
    monkeypatch.setattr(dre_mod, "EVENT_MARKER", tmp_path / "event.json")
    monkeypatch.setattr(dre_mod, "STATE", tmp_path)
    eng = D()
    calls = []
    monkeypatch.setattr(eng, "remediate", lambda **k: calls.append(k) or {"status": "REMEDIATED"})
    monkeypatch.setattr(eng, "_alert_signature", lambda: signature[0])
    return eng, calls, signature


def test_no_alert_does_not_run(tmp_path, monkeypatch):
    eng, calls, _ = _eng(tmp_path, monkeypatch, [(False, "none", {"critical_bars": 0, "lineage_changed": 0})])
    r = eng.run_on_alert()
    assert r["ran"] is False and r["status"] == "REMEDIATE_NO_ALERT" and calls == []


def test_alert_runs_once_then_dedups_and_throttles(tmp_path, monkeypatch):
    sig = [(True, "crit:AAAC|changed:5", {"critical_bars": 1, "lineage_changed": 5})]
    eng, calls, _ = _eng(tmp_path, monkeypatch, sig)

    # first sighting of the fault → remediates, with the SMALL event slice (API protection)
    r = eng.run_on_alert()
    assert r["ran"] is True and len(calls) == 1
    assert calls[0]["universe_limit"] == D.EVENT_UNIVERSE_LIMIT

    # SAME fault again → already handled, no re-fetch (can't hammer a persistent unfixable fault)
    r = eng.run_on_alert()
    assert r["ran"] is False and r["status"] == "REMEDIATE_ALERT_ALREADY_HANDLED" and len(calls) == 1

    # a DIFFERENT fault within the rate floor → throttled (still no second fetch)
    monkeypatch.setattr(eng, "_alert_signature",
                        lambda: (True, "crit:NEWSYM|changed:9", {"critical_bars": 1, "lineage_changed": 9}))
    r = eng.run_on_alert()
    assert r["ran"] is False and r["status"] == "REMEDIATE_EVENT_THROTTLED" and len(calls) == 1


def test_new_fault_runs_after_rate_floor(tmp_path, monkeypatch):
    eng, calls, _ = _eng(tmp_path, monkeypatch,
                         [(True, "crit:NEWSYM|changed:9", {"critical_bars": 1, "lineage_changed": 9})])
    # a stale marker (old ts, different fingerprint) → floor elapsed → a fresh fault remediates
    (tmp_path / "event.json").write_text(json.dumps({"ts": "2020-01-01T00:00:00", "fingerprint": "old"}))
    r = eng.run_on_alert()
    assert r["ran"] is True and len(calls) == 1


def test_disabled_never_runs(tmp_path, monkeypatch):
    eng, calls, _ = _eng(tmp_path, monkeypatch, [(True, "crit:X|changed:1", {"critical_bars": 1, "lineage_changed": 1})])
    monkeypatch.setenv("GREYLINE_DATA_AUTOREMEDIATE", "false")
    r = eng.run_on_alert()
    assert r["ran"] is False and r["status"] == "REMEDIATE_DISABLED" and calls == []


# ---- off-machine backup remediation (fold the backup failsafe into DataRemediation) -------------

class _FakeGit:
    """Minimal GitDataBackupEngine stand-in."""
    def __init__(self, hours, backup_ok=True):
        self._h = hours
        self._ok = backup_ok
        self.pushed = 0
    def hours_since(self):
        return self._h
    def backup(self, push=True):
        self.pushed += 1
        return {"status": "GIT_BACKUP_PUSHED" if self._ok else "GIT_BACKUP_PUSH_FAILED",
                "ok": self._ok, "pushed": self._ok, "files": 19, "expected": 19, "detail": "x"}


def _patch_git(monkeypatch, fake):
    import app.services.git_data_backup_engine as gmod
    monkeypatch.setattr(gmod, "GitDataBackupEngine", lambda: fake)


def test_backup_current_is_left_alone(tmp_path, monkeypatch):
    fake = _FakeGit(hours=1.5)
    _patch_git(monkeypatch, fake)
    action, alert = D()._remediate_backup(apply=True)
    assert action["status"] == "BACKUP_CURRENT" and action["ran"] is False
    assert fake.pushed == 0 and alert is None       # never re-pushes a fresh backup


def test_stale_backup_is_re_pushed(tmp_path, monkeypatch):
    fake = _FakeGit(hours=48.0)                       # > BACKUP_STALE_HOURS (26)
    _patch_git(monkeypatch, fake)
    action, alert = D()._remediate_backup(apply=True)
    assert action["ran"] is True and action["ok"] is True and fake.pushed == 1
    assert alert is None


def test_backup_never_pushed_yet_is_a_fault(tmp_path, monkeypatch):
    fake = _FakeGit(hours=None)                       # never backed up
    _patch_git(monkeypatch, fake)
    action, alert = D()._remediate_backup(apply=True)
    assert action["ran"] is True and fake.pushed == 1


def test_failed_re_push_raises_an_alert(tmp_path, monkeypatch):
    fake = _FakeGit(hours=48.0, backup_ok=False)
    _patch_git(monkeypatch, fake)
    action, alert = D()._remediate_backup(apply=True)
    assert action["ok"] is False and alert is not None and "FAILED" in alert


def test_stale_backup_shows_in_alert_signature(tmp_path, monkeypatch):
    _patch_git(monkeypatch, _FakeGit(hours=48.0))
    eng = D()
    # no bar/lineage faults, but a stale backup alone must raise an alert + appear in the fingerprint
    monkeypatch.setattr("app.services.price_bar_integrity_engine.PriceBarIntegrityEngine",
                        lambda: type("I", (), {"last_scan": lambda self: {}, "CRITICAL_TYPES": ()})())
    monkeypatch.setattr("app.services.price_bar_lineage_engine.PriceBarLineageEngine",
                        lambda: type("L", (), {"last_report": lambda self: {}})())
    has_alert, fp, detail = eng._alert_signature()
    assert has_alert is True and detail["backup_stale"] is True and "backup_stale:1" in fp
