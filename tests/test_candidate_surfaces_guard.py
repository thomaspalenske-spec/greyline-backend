"""The Opportunity Board flags degraded edges, and the reality guard catches regressions in the VRP /
Iron Condor / Opportunity surfaces — BOTH a thrown sleeve (empty) and a blank required field. No network.
"""

import json
from pathlib import Path

import app.services.unified_opportunity_board_engine as obe
from app.services.unified_opportunity_board_engine import UnifiedOpportunityBoardEngine
from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


# ---- board top-level degraded flag ----------------------------------------------------------------

def test_board_flags_degraded_when_a_group_errors(monkeypatch):
    eng = UnifiedOpportunityBoardEngine()
    monkeypatch.setattr(eng, "_momentum_group",
                        lambda: {"strategy": "Momentum-Reversal", "error": "boom", "candidates": []})
    monkeypatch.setattr(eng, "_earnings_group", lambda: {"strategy": "Earnings", "candidates": []})
    monkeypatch.setattr(eng, "_vrp_group", lambda: {"strategy": "VRP", "candidates": []})
    b = eng.board()
    assert b["degraded_edges"] == ["Momentum-Reversal"] and b["status"] == "OPPORTUNITY_BOARD_DEGRADED"


def test_board_clean_is_not_degraded(monkeypatch):
    eng = UnifiedOpportunityBoardEngine()
    for m in ("_momentum_group", "_earnings_group", "_vrp_group"):
        monkeypatch.setattr(eng, m, lambda: {"strategy": "X", "candidates": []})
    b = eng.board()
    assert b["degraded_edges"] == [] and b["status"] == "OPPORTUNITY_BOARD"


# ---- reality-guard invariant ----------------------------------------------------------------------

def _seed(tmp_path, monkeypatch, condors=None, sleeve_errors=None):
    monkeypatch.chdir(tmp_path)
    p = Path("app/data/condor_shadow/best_condors.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"condors": condors or [], "sleeve_errors": sleeve_errors or {}}))


def _condor():
    return {"symbol": "AMZN", "return_on_risk": 0.25, "dte": 50,
            "short_put": 215, "short_call": 280, "wing_put": 210, "wing_call": 285}


def _clean_board(self):
    return {"degraded_edges": [],
            "groups": [{"strategy": "VRP", "candidates": [{"symbol": "AMZN", "score": 99.2, "status": "ARMED"}]}]}


def test_guard_passes_when_all_surfaces_clean(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, condors=[_condor()])
    monkeypatch.setattr(obe.UnifiedOpportunityBoardEngine, "board", _clean_board)
    assert G()._check_candidate_surfaces_healthy()["ok"] is True


def test_guard_trips_on_ironcondor_sleeve_throw(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, condors=[_condor()], sleeve_errors={"VRP": "boom"})
    monkeypatch.setattr(obe.UnifiedOpportunityBoardEngine, "board", _clean_board)
    r = G()._check_candidate_surfaces_healthy()
    assert r["ok"] is False and "IronCondor[VRP]" in r["detail"]


def test_guard_trips_on_blank_condor_field(tmp_path, monkeypatch):
    c = _condor(); c["dte"] = None                        # the entry_dte-class regression
    _seed(tmp_path, monkeypatch, condors=[c])
    monkeypatch.setattr(obe.UnifiedOpportunityBoardEngine, "board", _clean_board)
    r = G()._check_candidate_surfaces_healthy()
    assert r["ok"] is False and "blank fields" in r["detail"]


def test_guard_trips_on_board_degraded_edge(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, condors=[_condor()])
    monkeypatch.setattr(obe.UnifiedOpportunityBoardEngine, "board",
                        lambda self: {"degraded_edges": ["Earnings IV-Crush"], "groups": []})
    r = G()._check_candidate_surfaces_healthy()
    assert r["ok"] is False and "Board[Earnings" in r["detail"]
