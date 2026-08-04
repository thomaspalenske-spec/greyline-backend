"""Off-box deadman heartbeat: pushes a liveness beacon to GitHub; records a marker the reality guard and
the GitHub Action read. No network — git ops are mocked.
"""

import json
import types

from app.services.deadman_heartbeat_engine import DeadmanHeartbeatEngine as D


def _wire(monkeypatch, tmp_path, push_rc=0):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(D, "REPO", repo)
    monkeypatch.setattr(D, "MARKER", tmp_path / "deadman_last.json")
    monkeypatch.setattr(D, "_ensure_repo", lambda self: (True, "https://origin"))

    def fake_git(self, *args, **k):
        rc = push_rc if "push" in args else 0
        return types.SimpleNamespace(returncode=rc, stdout="", stderr=("boom" if rc else ""))

    monkeypatch.setattr(D, "_git", fake_git)
    monkeypatch.setattr(D, "_context", lambda self: {})


def test_push_writes_heartbeat_and_marks(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    r = D().push()
    assert r["status"] == "DEADMAN_HEARTBEAT_PUSHED" and r["ok"] is True
    hb = json.loads((tmp_path / "repo" / "heartbeat.json").read_text())
    assert hb["epoch"] > 0 and hb["at"]
    marker = json.loads((tmp_path / "deadman_last.json").read_text())
    assert marker["pushed"] is True
    assert D().minutes_since() is not None and D().minutes_since() < 1


def test_push_failure_is_recorded_not_swallowed(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, push_rc=1)
    r = D().push()
    assert r["status"] == "DEADMAN_PUSH_FAILED" and r["ok"] is False
    marker = json.loads((tmp_path / "deadman_last.json").read_text())
    assert marker["pushed"] is False               # so the reality guard flags a broken beacon
    assert D().minutes_since() is None             # a failed push does not count as a live heartbeat


def test_push_if_due_gates_after_recent_push(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    monkeypatch.setenv("GREYLINE_DEADMAN_INTERVAL_MIN", "5")
    D().push()
    r = D().push_if_due()
    assert r["status"] == "DEADMAN_NOT_DUE"


def test_minutes_since_none_when_never_pushed(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    assert D().minutes_since() is None             # no marker yet
