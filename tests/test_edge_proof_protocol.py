"""Pre-registered edge-proof protocol: frozen per-sleeve hypothesis + required N + threshold + kill-rule,
rendering a BINDING verdict against the fill-truthful court. Tests the pre-registration discipline
(immutability / tamper-evidence), the mechanical verdict, and the condor dead-on-arrival cost screen."""

from app.services.edge_proof_protocol_engine import EdgeProofProtocolEngine as E


def _spec(required_n=30, threshold=2.0):
    return {"hypothesis": "h", "null": "n", "required_n": required_n,
            "threshold_ror_pct": threshold, "alpha": 0.05, "kill_rule": "k"}


# ---- pre-registration: freeze once, no silent goalpost-moving ----------------------------------

def test_bootstrap_registers_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "PROTOCOL_FILE", tmp_path / "p.json")
    r1 = E().bootstrap()
    assert r1["status"] == "PROTOCOLS_BOOTSTRAPPED" and set(r1["newly_registered"]) == set(E.DEFAULTS)
    r2 = E().bootstrap()
    assert r2["newly_registered"] == []            # nothing re-registered — frozen ones untouched


def test_register_refuses_silent_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "PROTOCOL_FILE", tmp_path / "p.json")
    e = E()
    assert e.register("premium_vrp", _spec(required_n=30))["status"] == "REGISTERED"
    # a second register WITHOUT force must NOT move the goalposts
    again = e.register("premium_vrp", _spec(required_n=5))
    assert again["status"] == "ALREADY_REGISTERED"
    # force records the change VISIBLY (superseded audit trail), never silently
    forced = e.register("premium_vrp", _spec(required_n=5), force=True)
    assert forced["status"] == "REGISTERED"
    assert "superseded" in e._load()["premium_vrp"]


def test_tamper_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "PROTOCOL_FILE", tmp_path / "p.json")
    e = E()
    e.register("trend", _spec(required_n=25))
    # simulate an editor changing the frozen required_n WITHOUT re-registering (the goalpost-move)
    data = e._load()
    data["trend"]["spec"]["required_n"] = 3
    e._save(data)
    # the content_hash no longer matches -> flagged TAMPERED in evaluate (checked via the hash directly)
    rec = e._load()["trend"]
    assert rec["content_hash"] != e._hash(rec["spec"])


# ---- mechanical verdict against the frozen protocol --------------------------------------------

def test_verdict_accumulating_below_n():
    v, _ = E._verdict(_spec(required_n=30), {"trades": 4, "ci95_return_on_risk_pct": [-5, 20]})
    assert v == "ACCUMULATING"


def test_verdict_proven_when_ci_above_threshold():
    v, _ = E._verdict(_spec(required_n=20, threshold=2.0), {"trades": 25, "ci95_return_on_risk_pct": [3.0, 9.0]})
    assert v == "PROVEN"


def test_verdict_retire_kill_rule():
    # reached N but the CI lower bound is not above the line -> the kill-rule fires
    v, _ = E._verdict(_spec(required_n=20, threshold=2.0), {"trades": 25, "ci95_return_on_risk_pct": [-1.0, 4.0]})
    assert v == "RETIRE"


def test_verdict_failing_early():
    # past the halfway mark and the CI is ALREADY entirely below the line -> early warning
    v, _ = E._verdict(_spec(required_n=20, threshold=2.0), {"trades": 12, "ci95_return_on_risk_pct": [-8.0, -1.0]})
    assert v == "FAILING_EARLY"


# ---- condor dead-on-arrival cost screen --------------------------------------------------------

def test_cost_screen_flags_dead_on_arrival(monkeypatch):
    import app.services.edge_proof_protocol_engine as mod
    # a thin-credit / high-qty condor: cost eats almost the whole credit -> DEAD_ON_ARRIVAL
    rows = [{"symbol": "PLTR", "credit_total": 165.0, "max_loss_total": 335.0, "quantity": 5,
             "legs": [1, 2, 3, 4]},
            {"symbol": "QQQ", "credit_total": 159.0, "max_loss_total": 341.0, "quantity": 1,
             "legs": [1, 2, 3, 4]}]

    class V:
        def _open_rows(self):
            return rows
    monkeypatch.setattr("app.services.conditional_vrp_short_premium_engine.ConditionalVRPShortPremiumEngine", V)
    out = E().condor_cost_screen()
    by = {c["symbol"]: c for c in out["condors"]}
    assert by["PLTR"]["screen"].startswith("DEAD_ON_ARRIVAL")
    assert by["QQQ"]["screen"].startswith("MARGINAL")
    # breakeven win-rate is credit-structure driven and always < the cost-inflated one
    assert by["QQQ"]["cost_inflated_breakeven_win_rate"] > by["QQQ"]["breakeven_win_rate"]
