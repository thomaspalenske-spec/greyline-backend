"""Root-E detectors: fantasy-close, stale decision caches, sanctioned-readout integrity.

Read-only invariants — they never place orders or mutate state.
"""

import json
import os
import time
from pathlib import Path

from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G


def _write_bars(symbol, n=300, mtime=None):
    """Give a symbol a TRADEABLE bar file (>= 253 lines) in the sandbox so the reality guard's tradeable-scope
    (which reads app/data/historical/<sym>_daily.csv) treats it as signal-relevant. The sandbox's app/data is
    fresh/empty, so tests asserting an alarm on a real symbol must provide its bars. Optional mtime (epoch) to
    control the 'restated since scan' check."""
    p = Path("app/data/historical") / f"{symbol}_daily.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("date,open,high,low,close,volume\n"
                 + "\n".join(f"2020-01-{i % 27 + 1:02d},1,1,1,1,1" for i in range(n)))
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


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
    # freshness tracks the RECOMPUTE flag (GREYLINE_BEST_CONDORS_ENABLED), not the VRP sleeve arm state
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_BEST_CONDORS_ENABLED", "true")   # producer ON -> cache should be fresh
    _write_cache("app/data/condor_shadow/best_condors.json", time.time() - 48 * 3600)   # 2 days old
    _write_cache("app/data/research/optionable_universe.json", time.time())
    r = G()._check_decision_caches_fresh()
    assert r["ok"] is False and "best-condors" in r["detail"]


def test_stale_condor_cache_ignored_when_recompute_disabled(tmp_path, monkeypatch):
    # recompute gated OFF (card retired) -> nothing refreshes best-condors, so its staleness is EXPECTED.
    # Regression guard for the 2026-08-14 false alarm: arming VRP must NOT resume this check.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_BEST_CONDORS_ENABLED", "false")
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")   # VRP armed, but it doesn't feed this cache
    _write_cache("app/data/condor_shadow/best_condors.json", time.time() - 224 * 3600)  # the real stale age
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


def test_stale_candidates_flag_when_scanwarm_on(tmp_path, monkeypatch):
    # WRONG-FLAG FIX (2026-08-17): staleness is gated on the PRODUCER (GREYLINE_MOMENTUM_SCAN_WARM), not on
    # momentum being armed — the scan-warm engine is what refreshes this snapshot. With the producer ON, a
    # >5-day-old snapshot is a real fault.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_MOMENTUM_SCAN_WARM", "true")      # producer on -> staleness is a real fault
    _write_candidates({"data_source": "TRADESTATION_LIVE_CACHED", "as_of": "2026-07-01"})   # very stale
    r = G()._check_data_source()
    assert r["ok"] is False and "suspect" in r["detail"]


def test_stale_candidates_ignored_when_scanwarm_off(tmp_path, monkeypatch):
    # wrong-flag fix: staleness is gated on the PRODUCER (MomentumScanWarmEngine / GREYLINE_MOMENTUM_SCAN_WARM),
    # OFF by default. With the producer off, nothing refreshes the snapshot, so staleness is EXPECTED, not a fault.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GREYLINE_MOMENTUM_SCAN_WARM", raising=False)
    monkeypatch.setenv("GREYLINE_MOMENTUM_ENABLED", "false")
    _write_candidates({"data_source": "TRADESTATION_LIVE_CACHED", "as_of": "2026-07-01"})
    r = G()._check_data_source()
    assert r["ok"] is True and "scan-warm off" in r["detail"]


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
    _write_bars("QQQM")                              # tradeable in the sandbox -> corruption is signal-relevant
    monkeypatch.setattr(P, "last_scan", lambda self: _scan(
        [{"symbol": "QQQM", "type": "NONPOSITIVE", "date": "d"}]))
    monkeypatch.setattr(G, "_active_universe", lambda self: {"QQQM", "IWM", "DBC"})
    r = G()._check_price_bars()
    assert r["ok"] is False and "QQQM" in r["detail"] and "TRADEABLE" in r["detail"]


def test_price_bars_momentum_armed_checks_everything(monkeypatch):
    from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine as P
    _write_bars("QQQM")                              # a TRADEABLE corrupt name still alarms with no universe scope
    monkeypatch.setattr(P, "last_scan", lambda self: _scan(
        [{"symbol": "QQQM", "type": "NONPOSITIVE", "date": "d"}]))
    monkeypatch.setattr(G, "_active_universe", lambda self: None)   # momentum armed -> no scope
    r = G()._check_price_bars()
    assert r["ok"] is False                          # any critical corruption in a tradeable name still alarms


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
    # tradeable + NOT restated since the scan: bar mtime (2026-08-01) is BEFORE the run timestamp (2026-08-09)
    _write_bars("QQQM", mtime=time.mktime(time.strptime("2026-08-01", "%Y-%m-%d")))
    monkeypatch.setattr(X, "last_run", lambda self: {
        "mismatched": 1, "mismatches": [{"symbol": "QQQM"}], "matched": 39, "checked": 40,
        "ok": False, "timestamp": "2026-08-09T00:00:00"})
    monkeypatch.setattr(G, "_active_universe", lambda self: {"QQQM", "IWM"})
    r = G()._check_price_bars_match_source()
    assert r["ok"] is False and "QQQM" in r["detail"]
