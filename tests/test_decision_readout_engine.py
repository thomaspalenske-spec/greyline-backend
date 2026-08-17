"""The sanctioned readout AGGREGATES canonical cached decisions, stamps provenance, never recomputes.

No network, no orders — every underlying reader is monkeypatched.
"""

import app.services.decision_readout_engine as dre
from app.services.decision_readout_engine import DecisionReadoutEngine


def _patch_all(monkeypatch, best=None, board=None, ew=None, uni=None, raise_best=False):
    import app.services.best_condors_engine as bc
    import app.services.unified_opportunity_board_engine as ob
    import app.services.execute_watch_engine as ew_mod
    import app.services.optionable_universe_engine as ou

    def _best(self, limit=12):
        if raise_best:
            raise RuntimeError("cache unreadable")
        return best if best is not None else {"timestamp": "2026-07-30T20:00:00", "condors": []}
    monkeypatch.setattr(bc.BestCondorsEngine, "cached", _best)
    monkeypatch.setattr(ob.UnifiedOpportunityBoardEngine, "board",
                        lambda self: board or {"timestamp": "2026-07-30T21:00:00", "groups": []})
    monkeypatch.setattr(ew_mod.ExecuteWatchEngine, "view",
                        lambda self: ew or {"candidates_as_of": "2026-07-30", "watch": []})
    monkeypatch.setattr(ou.OptionableUniverseEngine, "report",
                        lambda self, limit=300: uni or {"session_date": "2026-07-30", "tickers": []})


def test_readout_aggregates_all_sections(monkeypatch):
    _patch_all(monkeypatch)
    r = DecisionReadoutEngine().readout()
    titles = [s["title"] for s in r["sections"]]
    assert len(r["sections"]) == 4
    assert any("Best Iron Condors" in t for t in titles)
    assert any("Opportunity Board" in t for t in titles)
    assert r["status"] == "DECISION_READOUT_OK"


def test_live_quote_sections_are_flagged_point_in_time(monkeypatch):
    _patch_all(monkeypatch)
    r = DecisionReadoutEngine().readout()
    by_title = {s["title"]: s for s in r["sections"]}
    best = next(s for s in r["sections"] if "Best Iron Condors" in s["title"])
    uni = next(s for s in r["sections"] if "Optionable Universe" in s["title"])
    assert best["point_in_time"] is True and "precision" in best      # live UW quotes → flagged ±
    assert uni["point_in_time"] is False and "precision" not in uni    # daily screen → not point-in-time


def test_as_of_is_carried_from_the_owning_cache(monkeypatch):
    _patch_all(monkeypatch, best={"timestamp": "2026-07-30T20:00:00", "condors": [{"symbol": "AMZN"}]})
    r = DecisionReadoutEngine().readout()
    best = next(s for s in r["sections"] if "Best Iron Condors" in s["title"])
    assert best["as_of"] == "2026-07-30T20:00:00"                      # provenance, not invented


def test_a_broken_section_is_recorded_not_hidden(monkeypatch):
    _patch_all(monkeypatch, raise_best=True)
    r = DecisionReadoutEngine().readout()
    best = next(s for s in r["sections"] if "Best Iron Condors" in s["title"])
    assert best["status"] == "READOUT_SECTION_DEGRADED" and best["data"] is None
    assert "Best Iron Condors (ranked, buildable)" in r["degraded_sections"]
    assert r["status"] == "DECISION_READOUT_DEGRADED"                  # surfaced, never silent
