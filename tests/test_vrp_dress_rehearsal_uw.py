"""Pre-arm dress rehearsal proves the UW-priced CLOSE path (the 2026-08-13 unblock): a built condor is
only READY TO FIRE if UW can value its close (court-worthy realized P&L). Hermetic — plan/validate/UW
monkeypatched, places nothing, no network."""

import pytest

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def _con():
    return {"symbol": "SPY", "expiration": "2026-09-19", "iv_rank": 0.5,
            "legs": {"short_call": {"symbol": "SPY_SC", "action": "SELLTOOPEN"},
                     "wing_call": {"symbol": "SPY_WC", "action": "BUYTOOPEN"},
                     "short_put": {"symbol": "SPY_SP", "action": "SELLTOOPEN"},
                     "wing_put": {"symbol": "SPY_WP", "action": "BUYTOOPEN"}}}


@pytest.fixture
def _stub(monkeypatch):
    # dress_rehearsal() calls reload_env() which would reload .env and clobber the test's env overrides
    # (the .env-precedence trap) — neutralize it so GREYLINE_VRP_UW_CLOSE_PRICING under test sticks.
    monkeypatch.setattr("app.services.env_reload.reload_env", lambda *a, **k: None)
    monkeypatch.setattr(V, "plan", lambda self, **k: {"planned": [_con()], "skipped": []})
    monkeypatch.setattr(V, "validate_condor", lambda self, con: (True, {"structure": "ok"}, {"credit": 1.0}))
    monkeypatch.setattr(V, "condor_court_projection", lambda self, econ, sleeve: {"sleeve": sleeve})
    monkeypatch.setattr(V, "enabled", lambda self=None: False)   # disarmed (default)
    monkeypatch.setenv("GREYLINE_VRP_UW_CLOSE_PRICING", "true")


def test_close_court_worthy_when_uw_prices_the_close(monkeypatch, _stub):
    monkeypatch.setattr(V, "_uw_close_value", lambda self, row: (1.4, 0.4))     # UW can value the close
    r = V().dress_rehearsal()
    assert r["close_path_go"] is True and r["close_priceable_condors"] == 1
    assert r["rehearsed"][0]["close_court_worthy"] is True
    assert r["rehearsed"][0]["close_realized_basis"] == "uw_mid"
    assert r["verdict"].startswith("BUILD+CLOSE OK, NOT ARMED")          # sound + UW-priced close, just not armed
    assert "arm_plan" in r and "recommendation" in r["arm_plan"]


def test_not_court_worthy_when_uw_cannot_price_close(monkeypatch, _stub):
    monkeypatch.setattr(V, "_uw_close_value", lambda self, row: (None, None))    # UW can't value the close
    r = V().dress_rehearsal()
    assert r["close_path_go"] is False
    assert r["rehearsed"][0]["close_realized_basis"] == "ts_fallback"
    assert r["verdict"].startswith("BUILD OK but CLOSE NOT COURT-WORTHY")
    assert any("not court-worthy" in g.lower() for g in r["gate_blocks"])


def test_uw_close_pricing_off_is_gated(monkeypatch, _stub):
    monkeypatch.setenv("GREYLINE_VRP_UW_CLOSE_PRICING", "false")
    monkeypatch.setattr(V, "_uw_close_value", lambda self, row: (1.4, 0.4))
    r = V().dress_rehearsal()
    assert r["uw_close_pricing_on"] is False and r["close_path_go"] is False
    assert any("UW close pricing OFF" in g for g in r["gate_blocks"])
