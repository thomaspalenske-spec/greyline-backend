"""Index (XSP) condor planner: opt-in gate, strike-grid coarsening yields a tradeable wing, emits the
condor dict the shadow consumes, errors surfaced not swallowed. Chain + builder stubbed — no network."""

import pytest

from app.services.index_condor_plan_engine import IndexCondorPlanEngine as I


def _contract(side, strike, delta, bid, ask):
    return {"Side": side, "Legs": [{"Symbol": f"XSP 260918{'C' if side=='Call' else 'P'}{int(strike)}"}],
            "Bid": bid, "Ask": ask, "Delta": delta, "ImpliedVolatility": 0.15, "Vega": 0.1,
            "DailyOpenInterest": 1000}


def _fine_chain():
    # a fine $1 XSP ladder around ~780 spot: puts below, calls above
    cons = []
    for k in range(740, 761):      # puts 740..760
        d = -0.30 + (k - 740) * 0.01
        cons.append(_contract("Put", k, d, 2.0 - (760 - k) * 0.05, 2.1 - (760 - k) * 0.05))
    for k in range(800, 821):      # calls 800..820
        d = 0.30 - (k - 800) * 0.01
        cons.append(_contract("Call", k, d, 2.0 - (k - 800) * 0.05, 2.1 - (k - 800) * 0.05))
    return {"symbol": "XSP", "expiration": "2026-09-18", "contracts": cons, "status": "UW_CHAIN_READY"}


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("GREYLINE_INDEX_CONDOR_SHADOW", "true")
    yield


def test_disabled_by_default(monkeypatch):
    monkeypatch.setenv("GREYLINE_INDEX_CONDOR_SHADOW", "false")
    assert I.enabled() is False


def test_coarsen_drops_off_grid_strikes():
    import app.services.conditional_vrp_short_premium_engine as vrpmod
    b = vrpmod.ConditionalVRPShortPremiumEngine()
    cons = _fine_chain()["contracts"]
    kept = I._coarsen(cons, b, 10)
    strikes = {round(b._leg(c)["strike"]) for c in kept}
    assert strikes and all(k % 10 == 0 for k in strikes)      # only decade strikes survive
    assert len(kept) < len(cons)                              # $1 intermediates dropped


def test_plan_emits_shadow_condor_dict(monkeypatch):
    from app.services.uw_option_chain_engine import UWOptionChainEngine
    monkeypatch.setattr(UWOptionChainEngine, "get_chain_snapshot",
                        lambda self, sym, exp, **k: _fine_chain())
    monkeypatch.setattr(UWOptionChainEngine, "monthly_expiry",
                        staticmethod(lambda **k: "2026-09-18"))
    r = I().plan()
    assert r["status"] == "INDEX_CONDOR_PLAN_READY", r.get("errors")
    con = next(c for c in r["planned"] if c["symbol"] == "XSP")
    # exactly the keys the condor shadow reads
    assert con["symbol"] == "XSP" and con["expiration"] == "2026-09-18"
    for leg in ("short_call", "wing_call", "short_put", "wing_put"):
        assert con["legs"][leg]["symbol"] and con["legs"][leg]["bid"] > 0
    assert con["credit_per_condor"] > 0 and con["max_loss_total"] > 0 and con["quantity"] >= 1


def test_plan_iterates_every_configured_name(monkeypatch):
    # each of XSP + QQQ + IWM gets its own condor (per-name grid/cap iteration), build stubbed to isolate
    from app.services.uw_option_chain_engine import UWOptionChainEngine
    from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
    monkeypatch.setattr(UWOptionChainEngine, "get_chain_snapshot",
                        lambda self, sym, exp, **k: {"contracts": [{"Side": "Call"}]})
    monkeypatch.setattr(UWOptionChainEngine, "monthly_expiry", staticmethod(lambda **k: "2026-09-18"))
    monkeypatch.setattr(I, "_coarsen", staticmethod(lambda cons, b, g: cons))
    monkeypatch.setattr(ConditionalVRPShortPremiumEngine, "build_condor",
                        lambda self, sym, cons, **k: {"symbol": sym, "quantity": 1, "legs": {},
                                                      "credit_per_condor": 1.0, "max_loss_total": 400.0})
    r = I().plan()
    assert {c["symbol"] for c in r["planned"]} == set(I.NAME_CONFIG)     # XSP, QQQ, IWM, GLD all iterated
    tag = {c["symbol"]: c["_sleeve"] for c in r["planned"]}
    assert tag["GLD"] == "commodity_vrp" and tag["USO"] == "energy_vrp" and tag["TLT"] == "rates_vrp"
    assert tag["IBIT"] == "crypto_vrp"
    assert tag["XSP"] == "index_vrp" and tag["QQQ"] == "index_vrp"       # equity indices pool together


def test_chain_error_is_surfaced_not_swallowed(monkeypatch):
    from app.services.uw_option_chain_engine import UWOptionChainEngine
    monkeypatch.setattr(UWOptionChainEngine, "get_chain_snapshot",
                        lambda self, sym, exp, **k: {"contracts": [], "status": "UW_CHAIN_EMPTY"})
    monkeypatch.setattr(UWOptionChainEngine, "monthly_expiry", staticmethod(lambda **k: "2026-09-18"))
    r = I().plan()
    assert r["status"] == "INDEX_CONDOR_PLAN_EMPTY" and "XSP" in r["errors"]
