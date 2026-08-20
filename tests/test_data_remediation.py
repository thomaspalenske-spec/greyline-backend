"""DataRemediationEngine: gating, decision symbols, and the lineage SAFETY interlock. No TS, no writes."""

from pathlib import Path

import pytest

from app.services.data_remediation_engine import DataRemediationEngine as D

_REAL_HIST = Path(__file__).resolve().parents[1] / "app" / "data" / "historical"


def _fake_integrity(crit_symbol=None):
    class F:
        CRITICAL_TYPES = ("DUPLICATE_CROSS_SYMBOL",)

        def last_scan(self):
            issues = [{"symbol": crit_symbol, "type": "DUPLICATE_CROSS_SYMBOL"}] if crit_symbol else []
            return {"counts": {"DUPLICATE_CROSS_SYMBOL": len(issues)},
                    "critical_count": len(issues), "issues": issues}

        def repair_ohlc(self, dry_run=True):
            return {"repaired": 0}

        def scan(self, **k):
            return {}
    return F


def _fake_lineage(changed, calls):
    class F:
        def last_report(self):
            return {"changed_count": len(changed), "changed": changed}

        def snapshot(self, force=False):
            calls.append("snapshot")

        def verify(self, save=True):
            calls.append("verify")
            return {}
    return F


@pytest.fixture
def _no_refresh(monkeypatch):
    # no TS, no bar writes — isolate the lineage/decision logic
    monkeypatch.setattr(D, "_token", lambda self: ("tok", "http://x"))
    monkeypatch.setattr(D, "_decision_symbols", classmethod(lambda cls: []))
    monkeypatch.setattr(D, "_shadow_symbols", classmethod(lambda cls: []))
    monkeypatch.setattr(D, "_stale_symbols", classmethod(lambda cls, limit: []))
    yield


def test_enabled_default_true_and_toggle(monkeypatch):
    monkeypatch.delenv("GREYLINE_DATA_AUTOREMEDIATE", raising=False)
    assert D.enabled() is True
    monkeypatch.setenv("GREYLINE_DATA_AUTOREMEDIATE", "false")
    assert D.enabled() is False
    assert D().run_if_due()["status"] == "REMEDIATE_DISABLED"


def test_decision_symbols_include_spy_and_baskets(monkeypatch):
    monkeypatch.setattr("app.services.data_remediation_engine.BARS_DIR", _REAL_HIST)  # conftest sandboxes cwd
    syms = D._decision_symbols()
    assert "SPY" in syms and "QQQM" in syms and "SVXY" in syms


def test_shadow_symbols_include_overnight_etfs(monkeypatch):
    """The bar-dependent forward shadows must be in the ALWAYS-refresh set so they never accrue on stale bars.
    Regression guard for the 2026-08-20 stall where the overnight shadow's QQQ/IWM/DIA lagged ~3 days because
    only a rotating stalest slice was refreshed."""
    monkeypatch.setattr("app.services.data_remediation_engine.BARS_DIR", _REAL_HIST)  # conftest sandboxes cwd
    sh = D._shadow_symbols()
    # overnight-anomaly universe (the exact names that silently stalled) must be present
    assert {"SPY", "QQQ", "IWM", "DIA"} <= set(sh)
    # and the extended-ETF basket the extended-etf shadow marks on
    assert "MTUM" in sh or "QQQM" in sh


def _boom(*a, **k):
    raise RuntimeError("TS sandbox can't serve this symbol")


def test_uw_fallback_appends_when_ts_fails(monkeypatch, tmp_path):
    """When TradeStation can't serve a symbol, remediation falls back to Unusual Whales OHLC and appends the
    continuous bars (source tagged). This is the durable fix for the ~120 active names TS drops."""
    import app.services.data_remediation_engine as dre
    monkeypatch.setattr(dre, "BARS_DIR", tmp_path)
    (tmp_path / "ZZZ_daily.csv").write_text(
        "date,open,high,low,close,volume\n2026-08-17,10,10.2,9.9,10.0,100\n")
    monkeypatch.setattr(D, "_fetch_bars", staticmethod(_boom))
    monkeypatch.setattr(D, "_fetch_bars_uw", staticmethod(lambda sym: [
        {"date": "2026-08-17", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.05, "volume": 100},  # overlap OK
        {"date": "2026-08-18", "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 120},
    ]))
    r = D()._refresh_one("ZZZ", "http://x", "tok", "2026-08-19", apply=True)
    assert r["status"] == "APPENDED" and r["added"] == 1
    assert r["source"] == "unusual_whales" and r["through"] == "2026-08-18"


def test_uw_fallback_rejects_split_discontinuity(monkeypatch, tmp_path):
    """The cross-source continuity guard must reject a vendor split/adjustment mismatch (CSV 0.59 vs UW 11.80,
    the real BNZI reverse split) rather than stamp a false 20x gap into the series."""
    import app.services.data_remediation_engine as dre
    monkeypatch.setattr(dre, "BARS_DIR", tmp_path)
    (tmp_path / "SPLT_daily.csv").write_text(
        "date,open,high,low,close,volume\n2026-08-17,0.59,0.60,0.58,0.59,100\n")
    monkeypatch.setattr(D, "_fetch_bars", staticmethod(_boom))
    monkeypatch.setattr(D, "_fetch_bars_uw", staticmethod(lambda sym: [
        {"date": "2026-08-17", "open": 11.8, "high": 12.0, "low": 11.5, "close": 11.8, "volume": 100},  # 20x
        {"date": "2026-08-18", "open": 11.9, "high": 12.1, "low": 11.7, "close": 12.0, "volume": 120},
    ]))
    r = D()._refresh_one("SPLT", "http://x", "tok", "2026-08-19", apply=True)
    assert r["status"] == "UW_DISCONTINUITY" and r["added"] == 0


def test_lineage_auto_accepts_clean_restatement(monkeypatch, _no_refresh):
    calls = []
    monkeypatch.setattr("app.services.price_bar_integrity_engine.PriceBarIntegrityEngine", _fake_integrity(None))
    monkeypatch.setattr("app.services.price_bar_lineage_engine.PriceBarLineageEngine",
                        _fake_lineage([{"symbol": "AAA", "likely": "TARGETED_RESTATEMENT_OR_CORRUPTION"}], calls))
    r = D().remediate(apply=True, universe_limit=0, lineage="auto")
    assert r["actions"]["lineage"]["decision"] == "auto_accepted_clean_restatement"
    assert calls == ["snapshot", "verify"]              # re-baseline THEN refresh the report


def test_lineage_HELD_when_changed_symbol_also_corrupt(monkeypatch, _no_refresh):
    # the whole safety point: a changed symbol that is ALSO integrity-critical is NOT auto-accepted
    calls = []
    monkeypatch.setattr("app.services.price_bar_integrity_engine.PriceBarIntegrityEngine", _fake_integrity("BAD"))
    monkeypatch.setattr("app.services.price_bar_lineage_engine.PriceBarLineageEngine",
                        _fake_lineage([{"symbol": "BAD", "likely": "TARGETED_RESTATEMENT_OR_CORRUPTION"}], calls))
    r = D().remediate(apply=True, universe_limit=0, lineage="auto")
    assert r["actions"]["lineage"]["decision"] == "held_for_review"
    assert "snapshot" not in calls                       # never re-accepted
    assert any("LINEAGE held" in a for a in r["alerts"])


def test_lineage_force_accepts_regardless(monkeypatch, _no_refresh):
    calls = []
    monkeypatch.setattr("app.services.price_bar_integrity_engine.PriceBarIntegrityEngine", _fake_integrity("BAD"))
    monkeypatch.setattr("app.services.price_bar_lineage_engine.PriceBarLineageEngine",
                        _fake_lineage([{"symbol": "BAD", "likely": "TARGETED_RESTATEMENT_OR_CORRUPTION"}], calls))
    r = D().remediate(apply=True, universe_limit=0, lineage="force")
    assert r["actions"]["lineage"]["decision"] == "force_accepted"
    assert "snapshot" in calls
