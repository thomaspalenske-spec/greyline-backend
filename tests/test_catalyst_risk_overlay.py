"""Catalyst-aware tail defense: defer new premium into a scheduled vol event (Fed/CPI/jobs/FDA),
narrowly (only imminent, top-tier events), and FAIL OPEN on a calendar outage."""

from datetime import datetime, timedelta
from app.services.catalyst_risk_overlay_engine import CatalystRiskOverlayEngine


def _soon(days=0):
    return (datetime.utcnow().date() + timedelta(days=days)).isoformat() + "T12:30:00Z"


def test_defers_on_imminent_high_impact_macro(monkeypatch):
    e = CatalystRiskOverlayEngine()
    monkeypatch.setattr(e, "_economic", lambda: [
        {"event": "Core PCE index", "time": _soon(0)},
        {"event": "Consumer sentiment (final)", "time": _soon(0)},  # not top-tier
    ])
    monkeypatch.setattr(e, "_fda", lambda: [])
    r = e.defer_new_premium(tickers=["SPY"])
    assert r["defer"] is True and r["reason"] == "IMMINENT_HIGH_IMPACT_MACRO"
    assert any("PCE" in ev["event"] for ev in r["events"])


def test_does_not_defer_when_event_is_beyond_the_window(monkeypatch):
    e = CatalystRiskOverlayEngine()
    monkeypatch.setattr(e, "_economic", lambda: [{"event": "FOMC rate decision", "time": _soon(10)}])
    monkeypatch.setattr(e, "_fda", lambda: [])
    assert e.defer_new_premium(tickers=["SPY"])["defer"] is False


def test_low_impact_event_does_not_defer(monkeypatch):
    e = CatalystRiskOverlayEngine()
    monkeypatch.setattr(e, "_economic", lambda: [{"event": "Chicago Business Barometer (PMI)", "time": _soon(0)}])
    monkeypatch.setattr(e, "_fda", lambda: [])
    assert e.defer_new_premium()["defer"] is False


def test_second_tier_prints_do_not_defer_by_default(monkeypatch):
    # NARROWED 2026-08-14: retail sales / PPI / GDP no longer defer — they rarely gap the index and the
    # VRP condor wings cap the tail. Deferring on them had starved the Edge-proof clock.
    e = CatalystRiskOverlayEngine()
    monkeypatch.delenv("GREYLINE_CATALYST_BROAD_DEFER", raising=False)
    monkeypatch.setattr(e, "_fda", lambda: [])
    for ev in ("U.S. retail sales", "PPI (producer price index)", "GDP (advance)"):
        monkeypatch.setattr(e, "_economic", lambda ev=ev: [{"event": ev, "time": _soon(0)}])
        assert e.defer_new_premium(tickers=["SPY"])["defer"] is False, ev


def test_top_tier_prints_still_defer(monkeypatch):
    e = CatalystRiskOverlayEngine()
    monkeypatch.setattr(e, "_fda", lambda: [])
    for ev in ("CPI report", "FOMC rate decision", "Nonfarm payrolls"):
        monkeypatch.setattr(e, "_economic", lambda ev=ev: [{"event": ev, "time": _soon(0)}])
        assert e.defer_new_premium(tickers=["SPY"])["defer"] is True, ev


def test_broad_env_flag_restores_second_tier_defer(monkeypatch):
    e = CatalystRiskOverlayEngine()
    monkeypatch.setenv("GREYLINE_CATALYST_BROAD_DEFER", "true")
    monkeypatch.setattr(e, "_fda", lambda: [])
    monkeypatch.setattr(e, "_economic", lambda: [{"event": "U.S. retail sales", "time": _soon(0)}])
    assert e.defer_new_premium(tickers=["SPY"])["defer"] is True


def test_fda_catalyst_defers_only_the_named_ticker(monkeypatch):
    e = CatalystRiskOverlayEngine()
    monkeypatch.setattr(e, "_economic", lambda: [])
    monkeypatch.setattr(e, "_fda", lambda: [{"ticker": "MRNA", "description": "PDUFA date", "time": _soon(1)}])
    assert e.defer_new_premium(tickers=["MRNA"])["defer"] is True
    assert e.defer_new_premium(tickers=["SPY"])["defer"] is False   # indices unaffected by an FDA event


def test_fails_open_on_calendar_outage(monkeypatch):
    """A data outage must NOT halt the harvest — fail open, but say so."""
    e = CatalystRiskOverlayEngine()
    def boom(): raise RuntimeError("uw down")
    monkeypatch.setattr(e, "_economic", boom)
    r = e.defer_new_premium(tickers=["SPY"])
    assert r["defer"] is False and "FAIL_OPEN" in r["reason"]
