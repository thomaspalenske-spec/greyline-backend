"""Regression: the earnings dry-run must return `planned` as a LIST of condor dicts.

BestCondorsEngine and CondorShadowEngine read r["planned"] with an isinstance(list) guard, so returning
an int (len) silently dropped every earnings condor from the Iron Condor table. No network.
"""

from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine


def test_dryrun_planned_is_a_list(monkeypatch):
    eng = EarningsVolHarvestEngine()
    monkeypatch.setattr(eng, "enabled", lambda: True)
    monkeypatch.setattr(eng, "_candidates", lambda today=None: [])   # no candidates → planned == []
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    monkeypatch.setattr(eng, "_open_risk", lambda: 0.0)
    r = eng.open_positions(dry_run=True)
    assert isinstance(r["planned"], list)          # the condor LIST, not a count (the regression)
    assert r["planned_count"] == 0                 # count still available separately
