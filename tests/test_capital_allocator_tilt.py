"""Court-informed PRE-PROVEN allocation tilt — a bounded, sample-shrunk lean toward a below-gate sleeve's
accumulating court evidence. GATED OFF by default. Guardrails under test: never below the trade floor,
never above the gate (measured override wins), hard-capped, symmetric, stateless, and shows would_be even
when disabled. This exists so the allocator isn't blind to real evidence — WITHOUT treating a thin sample
as a verdict (the documented false-confidence trap)."""

import app.services.capital_allocator_engine as mod
from app.services.capital_allocator_engine import CapitalAllocatorEngine as C


def _court(monkeypatch, sleeves):
    from app.services.edge_persistence_engine import EdgePersistenceEngine
    monkeypatch.setattr(EdgePersistenceEngine, "realized_edge",
                        lambda self: {"min_trades_gate": 20, "sleeves": sleeves})


def _stub_env(monkeypatch, eng):
    # deterministic recommend(): fixed equity, no live-current reads
    monkeypatch.setattr(C, "_equity", lambda self: 10000.0)
    monkeypatch.setattr(C, "_current_allocs", lambda self, equity: {})
    monkeypatch.setattr(C, "_basis", lambda self: ("backtest_priors", 0))


def _rec(monkeypatch, sleeves, enabled):
    monkeypatch.setattr(mod, "getenv",
                        lambda k, d=None: ("true" if enabled else "false")
                        if k == "GREYLINE_COURT_ALLOC_TILT_ENABLED" else (d if d is not None else ""))
    eng = C()
    _stub_env(monkeypatch, eng)
    _court(monkeypatch, sleeves)
    return eng.recommend()


# vrp prior is evidence=1 (positive weight) — a good carrier for the tilt (trend/carry are evidence 2,
# earnings 0/probe, momentum -1/zero). Use vrp with a below-gate positive court sample.
def _vrp(n, mean=8.0, t=2.5):
    # the court sleeve key for the allocator's 'vrp' sleeve is 'premium_vrp' (via the allocator's _MAP)
    return {"premium_vrp": {"trades": n, "mean_return_on_risk_pct": mean, "t_stat": t}}


def test_disabled_by_default_no_tilt_but_shows_would_be(monkeypatch):
    rec = _rec(monkeypatch, _vrp(12), enabled=False)
    v = rec["sleeves"]["vrp"]
    assert rec["court_tilt_enabled"] is False and rec["court_tilt_applied_sleeves"] == []
    assert v["basis"] == "prior" and v["court_tilt"]["applied"] == 0.0
    assert v["court_tilt"]["would_be"] > 0.0            # transparency: shows what it WOULD do


def test_enabled_positive_evidence_tilts_up(monkeypatch):
    off = _rec(monkeypatch, _vrp(12), enabled=False)["sleeves"]["vrp"]["recommended_usd"]
    on = _rec(monkeypatch, _vrp(12), enabled=True)
    v = on["sleeves"]["vrp"]
    assert v["basis"] == "prior+tilt" and v["court_tilt"]["applied"] > 0.0
    assert "vrp" in on["court_tilt_applied_sleeves"]
    assert v["recommended_usd"] >= off                 # up-weighted vs disabled


def test_enabled_negative_evidence_tilts_down(monkeypatch):
    on = _rec(monkeypatch, _vrp(12, mean=-8.0, t=2.5), enabled=True)
    v = on["sleeves"]["vrp"]
    assert v["court_tilt"]["applied"] < 0.0 and v["basis"] == "prior+tilt"


def test_below_trade_floor_never_tilts(monkeypatch):
    on = _rec(monkeypatch, _vrp(5), enabled=True)      # 5 < TILT_MIN_TRADES
    v = on["sleeves"]["vrp"]
    assert v["court_tilt"]["applied"] == 0.0 and v["court_tilt"]["would_be"] == 0.0
    assert "floor" in v["court_tilt"]["reason"] and v["basis"] == "prior"


def test_hard_cap_on_extreme_signal(monkeypatch):
    # huge signal, just below the gate: confidence and shrink are both <=1, so the tilt is bounded BELOW
    # the cap by construction (max shrink at 19/20). The cap is a belt-and-suspenders ceiling it never
    # exceeds — a thin sample can never buy a full-strength tilt.
    applied = _rec(monkeypatch, _vrp(19, mean=50.0, t=99.0), enabled=True)["sleeves"]["vrp"]["court_tilt"]["applied"]
    assert 0 < applied <= C.TILT_MAX_FRAC and applied == round(0.95 * C.TILT_MAX_FRAC, 4)


def test_shrink_grows_with_sample(monkeypatch):
    near_floor = _rec(monkeypatch, _vrp(8, t=99.0), enabled=True)["sleeves"]["vrp"]["court_tilt"]["applied"]
    near_gate = _rec(monkeypatch, _vrp(19, t=99.0), enabled=True)["sleeves"]["vrp"]["court_tilt"]["applied"]
    assert 0 < near_floor < near_gate                  # more trades -> less shrink -> bigger tilt


def test_at_gate_is_measured_override_not_tilt(monkeypatch):
    # 20 trades with a PROVEN verdict -> measured path, not the tilt
    sleeves = {"premium_vrp": {"trades": 20, "mean_return_on_risk_pct": 8.0, "t_stat": 3.0,
                               "verdict": "PROVEN — cost-net edge > 0 at 95%"}}
    on = _rec(monkeypatch, sleeves, enabled=True)
    v = on["sleeves"]["vrp"]
    assert v["basis"] == "measured_proven" and (v["court_tilt"] or {}).get("applied", 0.0) == 0.0


def test_zero_weight_sleeve_is_not_funded_by_tilt(monkeypatch):
    # momentum prior is evidence -1 (zero weight). A positive below-gate sample must NOT fund it.
    on = _rec(monkeypatch, {"momentum": {"trades": 15, "mean_return_on_risk_pct": 9.0, "t_stat": 3.0}},
              enabled=True)
    m = on["sleeves"]["momentum"]
    assert m["recommended_usd"] == 0.0 and m["basis"] == "prior"   # tilt never funds a zeroed sleeve


def test_stateless_repeatable(monkeypatch):
    a = _rec(monkeypatch, _vrp(12), enabled=True)["sleeves"]["vrp"]["recommended_usd"]
    b = _rec(monkeypatch, _vrp(12), enabled=True)["sleeves"]["vrp"]["recommended_usd"]
    assert a == b                                      # no persistence, fully reversible
