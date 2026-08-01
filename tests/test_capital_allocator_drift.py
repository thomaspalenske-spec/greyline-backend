"""Allocation-drift alert: page (deduped) when a MEASURED court verdict has drifted the evidence-based
recommendation materially from the live budget — scoped to measured-basis sleeves only, not the standing
prior-vs-live divergence (which would be repeat noise)."""

from app.services.capital_allocator_engine import CapitalAllocatorEngine as C


def _rec(monkeypatch, sleeves, equity=10000.0):
    monkeypatch.setattr(C, "recommend", lambda self: {"equity": equity, "sleeves": sleeves})


def test_no_measured_drift_is_quiet(monkeypatch):
    # a HUGE drift but on a PRIOR basis (e.g. momentum) -> not alerted (operator already decided)
    _rec(monkeypatch, {"momentum": {"basis": "prior", "delta_usd": -2400,
                                    "current_usd": 2400, "recommended_usd": 0}})
    r = C().drift_alert(dispatch=False)
    assert r["status"] == "ALLOC_DRIFT_NONE" and r["drifts"] == []


def test_measured_proven_drift_flags_info(monkeypatch):
    _rec(monkeypatch, {"earnings": {"basis": "measured_proven", "delta_usd": 900,
                                    "current_usd": 500, "recommended_usd": 1400}})
    sent = {}
    import app.services.external_alert_engine as ae_mod
    monkeypatch.setattr(ae_mod, "ExternalAlertEngine", lambda: type("A", (), {
        "has_external_channel": lambda self: True, "dispatch": lambda self, **k: sent.update(k)})())
    r = C().drift_alert(dispatch=True)
    assert r["status"] == "ALLOC_DRIFT_FLAGGED" and r["drifts"][0]["sleeve"] == "earnings"
    assert sent["severity"] == "INFO" and sent["fingerprint"] == "ALLOC_DRIFT:earnings:measured_proven"
    assert "re-alloc" in sent["title"].lower()


def test_measured_decayed_drift_is_warning(monkeypatch):
    _rec(monkeypatch, {"trend": {"basis": "measured_decayed", "delta_usd": -2179,
                                 "current_usd": 2179, "recommended_usd": 0}})
    sent = {}
    import app.services.external_alert_engine as ae_mod
    monkeypatch.setattr(ae_mod, "ExternalAlertEngine", lambda: type("A", (), {
        "has_external_channel": lambda self: True, "dispatch": lambda self, **k: sent.update(k)})())
    C().drift_alert(dispatch=True)
    assert sent["severity"] == "WARNING"        # a decayed sleeve losing capital is a risk signal


def test_measured_but_small_drift_ignored(monkeypatch):
    _rec(monkeypatch, {"vrp": {"basis": "measured_proven", "delta_usd": 120,   # < threshold
                               "current_usd": 1200, "recommended_usd": 1320}})
    r = C().drift_alert(dispatch=False)
    assert r["status"] == "ALLOC_DRIFT_NONE"
