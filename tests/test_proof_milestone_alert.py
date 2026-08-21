"""Win-side proof-milestone alert: page ONCE as a sleeve crosses first_close / gate_reached / PROVEN, forward-
only (high-water), baselined silently on first run. Hermetic — proof_maturity + state file monkeypatched."""

import json

import pytest

from app.services.edge_persistence_engine import EdgePersistenceEngine as EP


@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.setattr(EP, "MILESTONE_STATE", tmp_path / "milestones.json")
    return tmp_path


def _mat(rows):
    return lambda self: {"sleeves": rows}


def test_first_run_baselines_without_paging(wired, monkeypatch):
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "low_vol", "current": 3, "gate": 20, "state": "ACCUMULATING"},
                              {"sleeve": "premium_vrp", "current": 0, "gate": 20, "state": "ACCUMULATING"}]))
    r = EP().proof_milestone_alert(dispatch=False)
    assert r["status"] == "PROOF_MILESTONE_BASELINED" and r["fired"] == []   # already-passed milestones don't burst-page
    assert r["milestones"] == {"low_vol": "first_close", "premium_vrp": "none"}


def test_vrp_first_close_fires_once(wired, monkeypatch):
    # baseline with VRP at 0 closes
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "premium_vrp", "current": 0, "gate": 20, "state": "ACCUMULATING"}]))
    EP().proof_milestone_alert(dispatch=False)                                # baseline
    # now VRP books its first close
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "premium_vrp", "current": 1, "gate": 20, "state": "ACCUMULATING",
                               "verdict": "ACCUMULATING (1/20)"}]))
    r = EP().proof_milestone_alert(dispatch=False)
    assert r["status"] == "PROOF_MILESTONE_FLAGGED"
    assert [(f["sleeve"], f["milestone"]) for f in r["fired"]] == [("premium_vrp", "first_close")]
    # idempotent: same state -> no re-fire
    assert EP().proof_milestone_alert(dispatch=False)["fired"] == []


def test_gate_reached_then_proven_ladder(wired, monkeypatch):
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "premium_vrp", "current": 5, "gate": 20, "state": "ACCUMULATING"}]))
    EP().proof_milestone_alert(dispatch=False)                                # baseline at first_close
    # reaches the gate
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "premium_vrp", "current": 20, "gate": 20, "state": "UNPROVEN"}]))
    r = EP().proof_milestone_alert(dispatch=False)
    assert [(f["sleeve"], f["milestone"]) for f in r["fired"]] == [("premium_vrp", "gate_reached")]
    # then PROVEN — the win
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "premium_vrp", "current": 22, "gate": 20, "state": "PROVEN",
                               "verdict": "PROVEN — cost-net edge > 0"}]))
    r = EP().proof_milestone_alert(dispatch=False)
    assert [(f["sleeve"], f["milestone"]) for f in r["fired"]] == [("premium_vrp", "proven")]


def test_forward_only_regress_does_not_repage(wired, monkeypatch):
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "s", "current": 20, "gate": 20, "state": "PROVEN"}]))
    EP().proof_milestone_alert(dispatch=False)                                # baseline at proven
    # a bad close regresses it below the gate — the WIN alert must NOT re-fire (that's decay_alert's job)
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "s", "current": 19, "gate": 20, "state": "UNPROVEN"}]))
    assert EP().proof_milestone_alert(dispatch=False)["fired"] == []
    # and if it re-crosses, it still doesn't re-page the already-reached milestone
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "s", "current": 21, "gate": 20, "state": "PROVEN"}]))
    assert EP().proof_milestone_alert(dispatch=False)["fired"] == []


def test_record_false_is_pure_read(wired, monkeypatch):
    """The route preview (record=False) must NOT mutate state — hitting it can't consume a real crossing."""
    monkeypatch.setattr(EP, "proof_maturity",
                        _mat([{"sleeve": "premium_vrp", "current": 1, "gate": 20, "state": "ACCUMULATING"}]))
    r = EP().proof_milestone_alert(dispatch=False, record=False)
    assert not (wired / "milestones.json").exists()                # no state file written on a preview
    # so the scheduler's real run still fires the crossing
    r2 = EP().proof_milestone_alert(dispatch=False, record=True)
    assert r2["status"] == "PROOF_MILESTONE_BASELINED"             # first real run baselines
