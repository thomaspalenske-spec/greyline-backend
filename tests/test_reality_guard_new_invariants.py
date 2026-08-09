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
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")   # condor sleeve ACTIVE -> cache matters
    _write_cache("app/data/condor_shadow/best_condors.json", time.time() - 48 * 3600)   # 2 days old
    _write_cache("app/data/research/optionable_universe.json", time.time())
    r = G()._check_decision_caches_fresh()
    assert r["ok"] is False and "best-condors" in r["detail"]


def test_stale_condor_cache_ignored_when_sleeve_retired(tmp_path, monkeypatch):
    # condor/VRP sleeve RETIRED -> nothing refreshes best-condors, so its staleness is EXPECTED, not a wedge
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "false")
    _write_cache("app/data/condor_shadow/best_condors.json", time.time() - 105 * 3600)  # very stale
    _write_cache("app/data/research/optionable_universe.json", time.time())
    r = G()._check_decision_caches_fresh()
    assert r["ok"] is True and "best-condors" not in r["detail"]


def test_fresh_caches_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_cache("app/data/condor_shadow/best_condors.json", time.time())
    _write_cache("app/data/research/optionable_universe.json", time.time())
    assert G()._check_decision_caches_fresh()["ok"] is True


def test_missing_cache_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                                    # no files at all
    assert G()._check_decision_caches_fresh()["ok"] is True        # warming state, own concern


# ---- DATA_SOURCE_REAL: disarmed momentum's stale candidate snapshot is not cry-wolf ---------------

def _write_candidates(obj):
    p = Path("app/data/momentum_reversal/top_candidates_cache.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


def test_stale_candidates_flag_when_momentum_armed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_MOMENTUM_ENABLED", "true")        # armed -> it WOULD trade on this data
    _write_candidates({"data_source": "TRADESTATION_LIVE_CACHED", "as_of": "2026-07-01"})   # very stale
    r = G()._check_data_source()
    assert r["ok"] is False and "suspect" in r["detail"]


def test_stale_candidates_ignored_when_momentum_disarmed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_MOMENTUM_ENABLED", "false")       # disarmed -> nothing refreshes/consumes it
    _write_candidates({"data_source": "TRADESTATION_LIVE_CACHED", "as_of": "2026-07-01"})
    r = G()._check_data_source()
    assert r["ok"] is True and "momentum disarmed" in r["detail"]


def test_fake_source_flags_even_when_disarmed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_MOMENTUM_ENABLED", "false")
    _write_candidates({"data_source": "FABRICATED", "as_of": "2026-08-09"})   # fresh but FAKE source
    r = G()._check_data_source()
    assert r["ok"] is False        # a fabricated source is wrong the moment momentum re-arms


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


# ---- PRICE_BARS scoped to the ACTIVE universe (inert corruption in untraded names doesn't alarm) ----

def _scan(issues, symbols_checked=2135):
    from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine as P
    counts = {}
    for i in issues:
        counts[i["type"]] = counts.get(i["type"], 0) + 1
    crit = sum(counts.get(t, 0) for t in P.CRITICAL_TYPES)
    return {"critical_count": crit, "counts": counts, "symbols_checked": symbols_checked,
            "issues": issues, "mode": "FULL", "scanned_at": "2026-08-09T00:00:00"}


def test_active_universe_is_none_when_momentum_armed(monkeypatch):
    monkeypatch.setenv("GREYLINE_MOMENTUM_ENABLED", "true")
    assert G()._active_universe() is None            # broad screener -> don't scope, check everything


def test_price_bars_inert_corruption_does_not_alarm(monkeypatch):
    from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine as P
    monkeypatch.setattr(P, "last_scan", lambda self: _scan(
        [{"symbol": "AAAC", "type": "NONPOSITIVE", "date": "d"},
         {"symbol": "ABI", "type": "OHLC_VIOLATION", "date": "d"}]))
    monkeypatch.setattr(G, "_active_universe", lambda self: {"QQQM", "IWM", "DBC"})
    r = G()._check_price_bars()
    assert r["ok"] is True and "inert" in r["detail"]


def test_price_bars_active_corruption_alarms(monkeypatch):
    from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine as P
    monkeypatch.setattr(P, "last_scan", lambda self: _scan(
        [{"symbol": "QQQM", "type": "NONPOSITIVE", "date": "d"}]))
    monkeypatch.setattr(G, "_active_universe", lambda self: {"QQQM", "IWM", "DBC"})
    r = G()._check_price_bars()
    assert r["ok"] is False and "QQQM" in r["detail"] and "ACTIVELY-TRADED" in r["detail"]


def test_price_bars_momentum_armed_checks_everything(monkeypatch):
    from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine as P
    monkeypatch.setattr(P, "last_scan", lambda self: _scan(
        [{"symbol": "AAAC", "type": "NONPOSITIVE", "date": "d"}]))
    monkeypatch.setattr(G, "_active_universe", lambda self: None)   # momentum armed -> no scope
    r = G()._check_price_bars()
    assert r["ok"] is False                          # any critical corruption still alarms


def test_match_source_inert_mismatch_does_not_alarm(monkeypatch):
    from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine as X
    monkeypatch.setattr(X, "last_run", lambda self: {
        "mismatched": 1, "mismatches": [{"symbol": "BAOS"}], "matched": 39, "checked": 40,
        "ok": False, "timestamp": "2026-08-09T00:00:00"})
    monkeypatch.setattr(G, "_active_universe", lambda self: {"QQQM", "IWM"})
    r = G()._check_price_bars_match_source()
    assert r["ok"] is True and "inert" in r["detail"]


def test_match_source_active_mismatch_alarms(monkeypatch):
    from app.services.price_bar_cross_source_engine import PriceBarCrossSourceEngine as X
    monkeypatch.setattr(X, "last_run", lambda self: {
        "mismatched": 1, "mismatches": [{"symbol": "QQQM"}], "matched": 39, "checked": 40,
        "ok": False, "timestamp": "2026-08-09T00:00:00"})
    monkeypatch.setattr(G, "_active_universe", lambda self: {"QQQM", "IWM"})
    r = G()._check_price_bars_match_source()
    assert r["ok"] is False and "QQQM" in r["detail"]
