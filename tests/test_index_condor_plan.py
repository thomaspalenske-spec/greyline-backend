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
    monkeypatch.setenv("GREYLINE_CONDOR_CONDITIONAL", "false")   # build/iteration tests exercise the BUILD path
    monkeypatch.setenv("GREYLINE_CONDOR_GEX_FILTER", "false")    # each gate is enabled per-test in isolation
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


def _stub_build(monkeypatch):
    # isolate the GATE from the build: chain + coarsen + build_condor all succeed trivially
    from app.services.uw_option_chain_engine import UWOptionChainEngine
    from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
    monkeypatch.setattr(UWOptionChainEngine, "get_chain_snapshot", lambda self, sym, exp, **k: {"contracts": [{"Side": "Call"}]})
    monkeypatch.setattr(UWOptionChainEngine, "monthly_expiry", staticmethod(lambda **k: "2026-09-18"))
    monkeypatch.setattr(I, "_coarsen", staticmethod(lambda cons, b, g: cons))
    monkeypatch.setattr(ConditionalVRPShortPremiumEngine, "build_condor",
                        lambda self, sym, cons, **k: {"symbol": sym, "quantity": 1, "legs": {},
                                                      "credit_per_condor": 1.0, "max_loss_total": 400.0})


def test_conditional_gate_opens_only_rich_iv(monkeypatch):
    # CONDITIONAL harvest: only names whose IV-proxy passes the rich-IV gate get a condor; rest SKIPPED (not errored)
    monkeypatch.setenv("GREYLINE_CONDOR_CONDITIONAL", "true")
    _stub_build(monkeypatch)
    monkeypatch.setattr(I, "_rich_iv", lambda self: {"GLD": 0.74})     # only gold rich today
    r = I().plan()
    assert [c["symbol"] for c in r["planned"]] == ["GLD"]              # only the rich name harvested
    assert r["planned"][0]["iv_rank"] == 0.74                          # entry richness recorded
    assert set(r["skipped"]) == set(I.NAME_CONFIG) - {"GLD"}           # the rest skipped, not errored
    assert not r["errors"]


def test_xsp_richness_proxies_off_spy(monkeypatch):
    # XSP has no UW IV series (cash-settled index) -> its richness is read off SPY
    monkeypatch.setenv("GREYLINE_CONDOR_CONDITIONAL", "true")
    _stub_build(monkeypatch)
    monkeypatch.setattr(I, "_rich_iv", lambda self: {"SPY": 0.80})     # SPY rich -> XSP should harvest
    r = I().plan()
    xsp = next(c for c in r["planned"] if c["symbol"] == "XSP")
    assert xsp["iv_rank"] == 0.80 and xsp["iv_proxy"] == "SPY"
    assert I.IV_PROXY["XSP"] == "SPY"


def test_gex_gate_opens_only_long_gamma(monkeypatch):
    # GAMMA-REGIME gate: with IV-gate off, only names whose proxy is LONG gamma (spot > flip) harvest;
    # short-gamma names are SKIPPED (condor-hostile). Records the entry gamma regime on the condor.
    monkeypatch.setenv("GREYLINE_CONDOR_GEX_FILTER", "true")
    _stub_build(monkeypatch)
    monkeypatch.setattr(I, "_gex_map", lambda self: {
        "GLD": {"gamma_flip": 399.78, "spot": 403.8, "long_gamma": True},    # long gamma -> harvest
        "SPY": {"gamma_flip": 779.51, "spot": 772.35, "long_gamma": False},  # short gamma -> skip (XSP proxy)
        "QQQ": {"gamma_flip": 749.0, "spot": 720.0, "long_gamma": False},
        "IWM": {"gamma_flip": 250.0, "spot": 245.0, "long_gamma": False},
        "USO": {"gamma_flip": 139.0, "spot": 125.0, "long_gamma": False},
        "TLT": {"gamma_flip": 90.0, "spot": 88.0, "long_gamma": False},
        "IBIT": {"gamma_flip": 38.8, "spot": 36.0, "long_gamma": False}})
    r = I().plan()
    assert [c["symbol"] for c in r["planned"]] == ["GLD"]
    con = r["planned"][0]
    assert con["long_gamma"] is True and con["entry_gamma_flip"] == 399.78 and con["entry_spot"] == 403.8
    assert set(r["skipped"]) == set(I.NAME_CONFIG) - {"GLD"}
    assert "gamma-flip" in r["skipped"]["USO"]      # names skipped for the GEX reason, not IV


def test_gex_fail_closed_without_read(monkeypatch):
    # no GEX data for a name -> do NOT open (fail-closed, gamma regime unconfirmed)
    monkeypatch.setenv("GREYLINE_CONDOR_GEX_FILTER", "true")
    _stub_build(monkeypatch)
    monkeypatch.setattr(I, "_gex_map", lambda self: {})    # total GEX read failure
    r = I().plan()
    assert r["planned"] == [] and set(r["skipped"]) == set(I.NAME_CONFIG)
    assert "fail-closed" in r["skipped"]["GLD"]


def test_chain_error_is_surfaced_not_swallowed(monkeypatch):
    from app.services.uw_option_chain_engine import UWOptionChainEngine
    monkeypatch.setattr(UWOptionChainEngine, "get_chain_snapshot",
                        lambda self, sym, exp, **k: {"contracts": [], "status": "UW_CHAIN_EMPTY"})
    monkeypatch.setattr(UWOptionChainEngine, "monthly_expiry", staticmethod(lambda **k: "2026-09-18"))
    r = I().plan()
    assert r["status"] == "INDEX_CONDOR_PLAN_EMPTY" and "XSP" in r["errors"]
