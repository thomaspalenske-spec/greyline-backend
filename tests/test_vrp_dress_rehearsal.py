"""VRP short-premium sleeve: pre-fire dress rehearsal + cap sensitivity (mirrors the earnings treatment).
VRP is continuous (not event-gated), harvesting variance premium on liquid index/ETFs — the fastest honest
path to filling the court's 20-trade gate. Both are read-only; validate_condor is the CANONICAL structure
audit the earnings sleeve delegates to."""

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V
import app.services.conditional_vrp_forward_panel_engine as panel_mod


def _condor(sym="IWM", sc=225.0, wc=230.0, sp=205.0, wp=200.0, credit=1.0, max_loss=400.0, ror=0.25, qty=1):
    return {"symbol": sym, "quantity": qty, "expiration": "2026-09-18", "iv_rank": 55,
            "legs": {"short_call": {"strike": sc}, "wing_call": {"strike": wc},
                     "short_put": {"strike": sp}, "wing_put": {"strike": wp}},
            "credit_per_condor": credit, "credit_total": credit * 100 * qty,
            "max_loss_total": max_loss, "return_on_risk": ror}


# ---------------- validate_condor (canonical) ----------------
def test_validate_condor_sound(monkeypatch):
    monkeypatch.setattr("app.services.sleeve_capital_budget_engine.SleeveCapitalBudgetEngine.per_condor_max_loss",
                        classmethod(lambda cls: 500.0))
    ok, checks, econ = V().validate_condor(_condor())
    assert ok is True and all(c["ok"] for c in checks) and econ["max_loss_total"] == 400.0


def test_validate_condor_inverted_wing_fails(monkeypatch):
    monkeypatch.setattr("app.services.sleeve_capital_budget_engine.SleeveCapitalBudgetEngine.per_condor_max_loss",
                        classmethod(lambda cls: 500.0))
    ok, checks, _ = V().validate_condor(_condor(sc=225.0, wc=220.0))     # call wing below short
    assert ok is False and {c["check"]: c["ok"] for c in checks}["defined_risk_call"] is False


# ---------------- dress rehearsal ----------------
def _prep_rehearsal(monkeypatch, planned, armed=True, skipped=None, uw_close=1.0):
    monkeypatch.setattr(V, "enabled", staticmethod(lambda: armed))
    monkeypatch.setattr(V, "plan",
                        lambda self, names=None, limit=None, max_scan=None: {"planned": planned, "skipped": skipped or [],
                                                              "candidates": len(planned), "free_slots": 5,
                                                              "total_defined_risk_usd": sum(p["max_loss_total"] for p in planned)})
    monkeypatch.setattr("app.services.sleeve_capital_budget_engine.SleeveCapitalBudgetEngine.per_condor_max_loss",
                        classmethod(lambda cls: 500.0))
    # UW close pricing is the 2026-08-13 unblock the rehearsal now proves. Neutralize reload_env (else it
    # reloads .env's flag) and stub the UW close valuation so the rehearsal exercises the close path
    # deterministically (uw_close=None simulates UW being unable to price the close).
    monkeypatch.setattr("app.services.env_reload.reload_env", lambda *a, **k: None)
    monkeypatch.setenv("GREYLINE_VRP_UW_CLOSE_PRICING", "true")
    # _uw_close_value now returns (close_value, close_spread); (None, None) when UW can't price the close.
    monkeypatch.setattr(V, "_uw_close_value",
                        lambda self, row: (uw_close, 0.4) if uw_close is not None else (None, None))


def test_dress_rehearsal_ready_when_armed(monkeypatch):
    _prep_rehearsal(monkeypatch, [_condor("IWM"), _condor("SMH")], armed=True)
    r = V().dress_rehearsal()
    assert r["build_go"] is True and r["valid_condors"] == 2 and r["armed"] is True
    assert r["close_path_go"] is True                       # UW prices both closes → court-worthy
    assert r["verdict"].startswith("READY TO FIRE") and r["sleeve"] == "premium_vrp"
    assert r["rehearsed"][0]["court_projection"]["sleeve"] == "premium_vrp"


def test_dress_rehearsal_build_ok_not_armed(monkeypatch):
    _prep_rehearsal(monkeypatch, [_condor("XLE")], armed=False)
    r = V().dress_rehearsal()
    assert r["build_go"] is True and r["verdict"].startswith("BUILD+CLOSE OK, NOT ARMED")
    assert any("DISARMED" in g for g in r["gate_blocks"])


def test_dress_rehearsal_no_build_not_ready(monkeypatch):
    _prep_rehearsal(monkeypatch, [], armed=True, skipped=[{"ticker": "IWM", "skip": "vega budget"}])
    r = V().dress_rehearsal()
    assert r["build_go"] is False and r["verdict"].startswith("NOT READY")
    assert r["plan_skipped"] == [{"ticker": "IWM", "skip": "vega budget"}]


def test_dress_rehearsal_bad_structure_not_ready(monkeypatch):
    _prep_rehearsal(monkeypatch, [_condor("IWM", sc=225.0, wc=220.0)], armed=True)  # inverted call wing
    r = V().dress_rehearsal()
    assert r["valid_condors"] == 0 and r["build_go"] is False


# ---------------- cap sensitivity ----------------
def _prep_cap(monkeypatch, per_name, equity=10000.0, current_cap=500.0):
    monkeypatch.setattr(V, "_open_symbols", lambda self: set())
    monkeypatch.setattr(panel_mod.ConditionalVRPForwardPanelEngine, "harvest_candidates",
                        lambda self, names=None: [{"ticker": t} for t in per_name])
    monkeypatch.setattr(V, "_chain", lambda self, t: ("2026-09-18", ["x"]))
    def _build(self, symbol, contracts, put_delta=None, call_delta=None, max_loss_cap=None):
        spec = per_name[symbol]
        if spec.get("skip"):
            return {"skip": spec["skip"]}
        mlp = spec["min_max_loss"]
        return {"symbol": symbol, "max_loss_per_condor": mlp, "credit_per_condor": 1.0,
                "return_on_risk": round(100.0 / mlp, 3)}
    monkeypatch.setattr(V, "build_condor", _build)
    monkeypatch.setattr("app.services.sleeve_capital_budget_engine.SleeveCapitalBudgetEngine._live",
                        classmethod(lambda cls: (equity, equity)))
    monkeypatch.setattr("app.services.sleeve_capital_budget_engine.SleeveCapitalBudgetEngine.per_condor_max_loss",
                        classmethod(lambda cls: current_cap))


def test_cap_sensitivity_sweep(monkeypatch):
    _prep_cap(monkeypatch, {"IWM": {"min_max_loss": 420.0}, "SMH": {"min_max_loss": 480.0},
                            "XLE": {"min_max_loss": 900.0}})
    r = V().cap_sensitivity(caps=[500.0, 1000.0])
    assert r["sleeve"] == "premium_vrp" and r["tradeable_now"] == ["IWM", "SMH"]
    sweep = {s["cap_usd"]: s for s in r["cap_sweep"]}
    assert sweep[500.0]["tradeable"] == ["IWM", "SMH"] and sweep[1000.0]["tradeable"] == ["IWM", "SMH", "XLE"]


def test_cap_sensitivity_skips_open_and_structural(monkeypatch):
    _prep_cap(monkeypatch, {"IWM": {"min_max_loss": 420.0}, "XLE": {"skip": "credit below floor"}})
    monkeypatch.setattr(V, "_open_symbols", lambda self: {"IWM"})     # IWM already open -> excluded
    r = V().cap_sensitivity(caps=[500.0])
    assert r["tradeable_now"] == [] and "XLE" in [u["ticker"] for u in r["structurally_untradeable"]]
