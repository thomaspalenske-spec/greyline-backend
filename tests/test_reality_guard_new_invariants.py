"""Root-E detectors: fantasy-close, stale decision caches, sanctioned-readout integrity.

Read-only invariants — they never place orders or mutate state.
"""

import json
import time
from pathlib import Path

from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


# ---- EXITS_FILLED_NOT_INTENDED (Root A guard) -----------------------------------------------------

def _view(*syms):
    return {"positions": [{"symbol": s} for s in syms]}


def test_fantasy_close_is_flagged_critical(monkeypatch):
    g = G()
    monkeypatch.setattr(g, "_recently_closed_symbols", lambda days: {"AAPL"})
    monkeypatch.setattr(g, "_recently_closed_realized", lambda days: {"AAPL": 312.50})  # real $ banked
    monkeypatch.setattr(g, "managed_symbols", lambda: set())
    r = g._check_exits_filled_not_intended(_view("AAPL", "MSFT"))   # AAPL closed w/ P&L but broker holds
    assert r["severity"] == "critical" and r["ok"] is False        # fabricated realized -> red fantasy
    assert r["suspects"] == ["AAPL"]


def test_residual_close_with_no_pnl_is_warning_not_fantasy(monkeypatch):
    """A close the broker still holds but that banked NO realized dollars (e.g. an illiquid wing the
    flatten marked closed but couldn't sell) is a benign reconciliation lag — amber warning, not red
    fantasy. Regression guard for the 2026-08-04 NRG residual false-red."""
    g = G()
    monkeypatch.setattr(g, "_recently_closed_symbols", lambda days: {"NRG 260807C152.5"})
    monkeypatch.setattr(g, "_recently_closed_realized", lambda days: {"NRG 260807C152.5": 0.0})  # None->0
    monkeypatch.setattr(g, "managed_symbols", lambda: set())
    r = g._check_exits_filled_not_intended(_view("NRG 260807C152.5", "MSFT"))
    assert r["severity"] == "warning" and r["ok"] is False         # surfaced, but NOT a red fantasy
    assert r["suspects"] == ["NRG 260807C152.5"]
    assert "NO P&L" in r["detail"]


def test_rebought_symbol_is_not_a_fantasy_close(monkeypatch):
    g = G()
    monkeypatch.setattr(g, "_recently_closed_symbols", lambda days: {"AAPL"})
    monkeypatch.setattr(g, "managed_symbols", lambda: {"AAPL"})    # re-opened → legitimately held
    r = g._check_exits_filled_not_intended(_view("AAPL"))
    assert r["ok"] is True


def test_closed_and_actually_flat_is_clean(monkeypatch):
    g = G()
    monkeypatch.setattr(g, "_recently_closed_symbols", lambda days: {"AAPL"})
    monkeypatch.setattr(g, "managed_symbols", lambda: set())
    r = g._check_exits_filled_not_intended(_view("MSFT"))          # broker no longer holds AAPL
    assert r["ok"] is True and r["suspects"] == []


# ---- DECISION_CACHES_FRESH ------------------------------------------------------------------------

def _write_cache(rel, epoch):
    p = Path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"computed_epoch": epoch}))


def test_stale_condor_cache_trips_the_warning(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cache("app/data/condor_shadow/best_condors.json", time.time() - 48 * 3600)   # 2 days old
    _write_cache("app/data/research/optionable_universe.json", time.time())
    r = G()._check_decision_caches_fresh()
    assert r["ok"] is False and "best-condors" in r["detail"]


def test_fresh_caches_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cache("app/data/condor_shadow/best_condors.json", time.time())
    _write_cache("app/data/research/optionable_universe.json", time.time())
    assert G()._check_decision_caches_fresh()["ok"] is True


def test_missing_cache_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                    # no files at all
    assert G()._check_decision_caches_fresh()["ok"] is True        # warming state, own concern


# ---- READOUT_INTEGRITY ----------------------------------------------------------------------------

def test_degraded_readout_section_trips_the_warning(monkeypatch):
    import app.services.decision_readout_engine as dre
    monkeypatch.setattr(dre.DecisionReadoutEngine, "readout",
                        lambda self, **k: {"degraded_sections": ["Best Iron Condors (ranked, buildable)"]})
    r = G()._check_readout_integrity()
    assert r["ok"] is False and "Best Iron Condors" in r["detail"]


def test_clean_readout_passes(monkeypatch):
    import app.services.decision_readout_engine as dre
    monkeypatch.setattr(dre.DecisionReadoutEngine, "readout", lambda self, **k: {"degraded_sections": []})
    assert G()._check_readout_integrity()["ok"] is True
