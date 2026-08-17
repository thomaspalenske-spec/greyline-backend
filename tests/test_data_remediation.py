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
