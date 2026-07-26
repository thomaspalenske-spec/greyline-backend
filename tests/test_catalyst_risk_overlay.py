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
