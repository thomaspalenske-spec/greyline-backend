"""Hermetic tests for AdaptiveDTESelectionEngine — no live chain, no network.

Verifies the guardrails that matter: the tenor is always inside the band (so the old 7-DTE /
MANAGE_DTE collision cannot recur), adaptive picks the EV-best expiration, and every degraded path
falls back to a safe band-clamped static choice rather than something pathological.
"""

from datetime import date

import pytest

from app.services.adaptive_dte_selection_engine import AdaptiveDTESelectionEngine as ENG

MON = date(2026, 7, 27)      # a Monday; band default 28..56 DTE


@pytest.fixture(autouse=True)
def _clear_cache_and_band(monkeypatch):
    ENG._cache.clear()
    monkeypatch.setenv("GREYLINE_DTE_BAND_MIN", "28")
    monkeypatch.setenv("GREYLINE_DTE_BAND_MAX", "56")
    monkeypatch.setenv("GREYLINE_DTE_TARGET", "42")
    yield
    ENG._cache.clear()


def _exps(dtes):
    return [(MON.fromordinal(MON.toordinal() + d)).isoformat() for d in dtes]


def _dte(iso):
    return (date.fromisoformat(iso) - MON).days


def test_disabled_returns_static_target_in_band(monkeypatch):
    monkeypatch.setenv("GREYLINE_ADAPTIVE_DTE_ENABLED", "false")
    eng = ENG()
    monkeypatch.setattr(eng, "_list_expirations", lambda s: _exps([7, 28, 35, 42, 49, 56, 90]))
    # scoring must NOT be consulted when disabled
    monkeypatch.setattr(eng, "_score_tenor", lambda s, e: (_ for _ in ()).throw(AssertionError("scored while disabled")))
    chosen = eng.select("SPY", today=MON)
    assert _dte(chosen) == 42                     # nearest listed to the 42 target, inside the band


def test_enabled_picks_ev_best_within_band(monkeypatch):
    monkeypatch.setenv("GREYLINE_ADAPTIVE_DTE_ENABLED", "true")
    eng = ENG()
    monkeypatch.setattr(eng, "_list_expirations", lambda s: _exps([7, 28, 42, 56, 90]))
    scores = {_exps([28])[0]: 0.10, _exps([42])[0]: 0.35, _exps([56])[0]: 0.20}

    def fake_score(sym, exp):
        return {"ev_per_risk": scores[exp], "pop": 0.7, "credit_total": 100.0,
                "max_loss_total": 250.0, "ev": scores[exp] * 250.0, "return_on_risk": 0.4}
    monkeypatch.setattr(eng, "_score_tenor", fake_score)
    chosen = eng.select("SPY", today=MON)
    assert _dte(chosen) == 42                     # the highest ev_per_risk candidate


def test_never_returns_below_band_floor(monkeypatch):
    # even if the only listed expiries are short-dated, the result must be >= band MIN when any
    # eligible expiry exists, and never a sub-floor literal
    monkeypatch.setenv("GREYLINE_ADAPTIVE_DTE_ENABLED", "true")
    eng = ENG()
    monkeypatch.setattr(eng, "_list_expirations", lambda s: _exps([1, 3, 7, 30]))
    monkeypatch.setattr(eng, "_score_tenor", lambda s, e: {"ev_per_risk": 0.2, "pop": 0.7,
                        "credit_total": 90.0, "max_loss_total": 250.0, "ev": 50.0, "return_on_risk": 0.3})
    chosen = eng.select("SPY", today=MON)
    assert _dte(chosen) == 30                     # the only in-band expiry; the 1/3/7 are excluded


def test_empty_band_falls_back_to_nearest_above_min(monkeypatch):
    # nothing inside the band: pick the nearest listed expiry at/above MIN, never a weekly
    monkeypatch.setenv("GREYLINE_ADAPTIVE_DTE_ENABLED", "true")
    eng = ENG()
    monkeypatch.setattr(eng, "_list_expirations", lambda s: _exps([3, 10, 70, 100]))
    monkeypatch.setattr(eng, "_score_tenor", lambda s, e: None)
    chosen = eng.select("SPY", today=MON)
    assert _dte(chosen) == 70                     # first listed >= MIN(28), not the 3/10 weeklies


def test_all_untradeable_falls_back_to_static_target(monkeypatch):
    monkeypatch.setenv("GREYLINE_ADAPTIVE_DTE_ENABLED", "true")
    eng = ENG()
    monkeypatch.setattr(eng, "_list_expirations", lambda s: _exps([28, 42, 56]))
    monkeypatch.setattr(eng, "_score_tenor", lambda s, e: None)   # every tenor untradeable
    chosen = eng.select("SPY", today=MON)
    assert _dte(chosen) == 42                     # safe static target, still in band


def test_ev_math():
    # pop = 1 - 0.25 - 0.15 = 0.60 ; ev = 0.6*(200*0.5) - 0.4*300 = 60 - 120 = -60
    con = {"short_put_delta": -0.25, "short_call_delta": 0.15,
           "credit_total": 200.0, "max_loss_total": 300.0, "return_on_risk": 0.66}
    ev = ENG._ev(con)
    assert ev["pop"] == 0.60
    assert ev["ev"] == -60.0
    assert ev["ev_per_risk"] == round(-60.0 / 300.0, 4)


def test_ev_rejects_zero_risk():
    assert ENG._ev({"short_put_delta": -0.2, "short_call_delta": 0.1,
                    "credit_total": 100.0, "max_loss_total": 0.0}) is None


def test_scorecard_is_inspectable(monkeypatch):
    monkeypatch.setenv("GREYLINE_ADAPTIVE_DTE_ENABLED", "true")
    eng = ENG()
    monkeypatch.setattr(eng, "_list_expirations", lambda s: _exps([28, 42, 56]))
    monkeypatch.setattr(eng, "_score_tenor", lambda s, e: {"ev_per_risk": _dte(e) / 100.0, "pop": 0.7,
                        "credit_total": 100.0, "max_loss_total": 250.0, "ev": 10.0, "return_on_risk": 0.3})
    sc = eng.scorecard("SPY", today=MON)
    assert sc["band"] == (28, 56)
    assert len(sc["candidates"]) == 3
    assert _dte(sc["chosen_expiration"]) == 56     # highest ev_per_risk (dte/100) among candidates
    assert all("dte" in c for c in sc["candidates"])
