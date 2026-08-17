"""Low-vol / BAB sleeve: inverse-volatility weighting (more capital to lower-vol names), fail-safe when
price data is missing (no weights -> no targets -> no trades), and gated OFF by default."""

from app.services.low_volatility_engine import LowVolatilityEngine as L


def test_inverse_vol_weighting(monkeypatch):
    monkeypatch.setattr(L, "_realized_vol",
                        lambda self, s: {"USMV": 0.10, "SPLV": 0.10, "EFAV": 0.20, "XMLV": 0.40}.get(s))
    w, vols = L()._weights()
    assert abs(sum(w.values()) - 1.0) < 1e-9                 # weights normalize
    assert w["USMV"] > w["EFAV"] > w["XMLV"]                 # lower vol -> more weight (the low-vol tilt)
    assert abs(w["USMV"] - w["SPLV"]) < 1e-9                 # equal vol -> equal weight


def test_missing_data_fails_safe(monkeypatch):
    monkeypatch.setattr(L, "_realized_vol", lambda self, s: None)   # no usable vol for any name
    w, _ = L()._weights()
    assert w == {}                                          # no targets -> the sleeve never trades on no data


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GREYLINE_LOW_VOL_ENABLED", raising=False)
    assert L.enabled() is False
    assert L().run_cycle()["status"] == "LOW_VOL_DISABLED"   # short-circuits before any broker call


def test_registered_in_edge_proof_protocol():
    from app.services.edge_proof_protocol_engine import EdgeProofProtocolEngine
    assert "low_vol" in EdgeProofProtocolEngine.DEFAULTS      # has a pre-registered kill-rule from day one


# --- diversification floor: never concentrate the budget into a subset with fresh data (2026-08-11:
#     3-of-4 names had unusable vol one cycle -> ~100% into XMLV -> 20 held vs a 3-share target) ---

def test_skips_when_too_few_fresh_names(monkeypatch):
    # only 2 of 4 names have usable vol -> below MIN_USABLE_NAMES(3) -> skip (no weights, no trade)
    monkeypatch.setattr(L, "_realized_vol",
                        lambda self, s: {"USMV": 0.10, "SPLV": 0.12}.get(s))   # EFAV/XMLV -> None
    w, _ = L()._weights()
    assert w == {}


def test_one_fresh_name_never_gets_the_whole_budget(monkeypatch):
    # the exact XMLV pathology: if it DID pass the floor, no single name may exceed MAX_NAME_WEIGHT
    monkeypatch.setattr(L, "MIN_USABLE_NAMES", 1)                               # relax the floor to test the cap
    monkeypatch.setattr(L, "_realized_vol", lambda self, s: 0.10 if s == "XMLV" else None)
    w, _ = L()._weights()
    assert w.get("XMLV", 0) <= L.MAX_NAME_WEIGHT + 1e-9                         # capped, NOT 1.0


def test_no_name_exceeds_cap_with_skewed_vol(monkeypatch):
    # one ultra-low-vol name would dominate; the cap must bind
    monkeypatch.setattr(L, "_realized_vol",
                        lambda self, s: {"USMV": 0.02, "SPLV": 0.40, "EFAV": 0.40, "XMLV": 0.40}.get(s))
    w, _ = L()._weights()
    assert max(w.values()) <= L.MAX_NAME_WEIGHT + 1e-9 and len(w) == 4


def test_resting_buys_counted_in_per_sleeve_headroom(monkeypatch):
    # 8 XMLV filled + 12 XMLV resting -> headroom must see 20 (else consecutive cycles stack the buy)
    from app.services.low_volatility_engine import LowVolatilityEngine as L
    import app.services.sleeve_trade_ledger_engine as sled
    import app.services.sleeve_capital_budget_engine as scb
    import app.services.in_flight_orders_engine as ifo
    monkeypatch.setattr(L, "enabled", staticmethod(lambda: True))
    monkeypatch.setattr(sled.SleeveTradeLedgerEngine, "reconcile_plan", lambda self, *a, **k: None)
    captured = {}
    monkeypatch.setattr(scb.SleeveCapitalBudgetEngine, "deployment_headroom_usd",
                        staticmethod(lambda sleeve, deployed: (captured.__setitem__("d", deployed) or 1e6)))
    monkeypatch.setattr(ifo.InFlightOrdersEngine, "snapshot",
                        classmethod(lambda cls, *a, **k: {"ok": True, "net": {"XMLV": 12}}))
    e = L()
    e.plan = lambda: {"legs": [{"symbol": "XMLV", "bid": 68.0, "ask": 68.1, "held": 8, "last": 68.0,
                                "delta_shares": 0, "delta_usd": 0.0}], "deployed_usd": 544.0}
    e.run_cycle(is_regular_session=True, dry_run=True)
    assert abs(captured["d"] - 20 * 68.0) < 1e-6            # 8 filled + 12 resting = 20, not just 8
