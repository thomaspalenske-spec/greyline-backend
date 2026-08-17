"""Gated auto-apply of the measured allocation. Steps the sleeve %-of-equity budgets toward the
allocator recommendation — evidence-only, capped per step, reversible via an override file, GATED OFF by
default. Guardrails under test: no-op when disabled, never moves a static-prior sleeve, per-step cap,
override precedence (env pin > override > default), reversibility, once-daily/after-close scheduler hook."""

import json

import app.services.sleeve_budget_autoapply_engine as mod
from app.services.sleeve_budget_autoapply_engine import SleeveBudgetAutoApplyEngine as A
from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as B


def _point_files(monkeypatch, tmp_path):
    ov = tmp_path / "overrides.json"
    monkeypatch.setattr(B, "OVERRIDE_FILE", ov)
    monkeypatch.setattr(A, "OVERRIDE_FILE", ov)
    monkeypatch.setattr(A, "HISTORY", tmp_path / "hist.jsonl")
    monkeypatch.setattr(A, "MARKER", tmp_path / ".marker")
    # clear any real sleeve-pct env pins so pct() resolves to override/default deterministically
    for k in ("MOMENTUM", "TREND", "VOL_CARRY", "VRP", "EARNINGS", "MANAGED_FUTURES"):
        monkeypatch.delenv("GREYLINE_%s_ALLOC_PCT" % k, raising=False)
    return ov


def _rec(monkeypatch, sleeves, basis="measured (court)"):
    from app.services.capital_allocator_engine import CapitalAllocatorEngine
    monkeypatch.setattr(CapitalAllocatorEngine, "recommend",
                        lambda self: {"basis": basis, "sleeves": sleeves})


def _enable(monkeypatch, on):
    monkeypatch.setattr(mod, "getenv",
                        lambda k, d="": ("true" if on else "false")
                        if k == "GREYLINE_ALLOC_AUTOAPPLY_ENABLED" else d)


def _vrp_rec(recommended_pct, basis="measured_proven"):
    return {"vrp": {"recommended_pct": recommended_pct, "basis": basis},
            "trend": {"recommended_pct": 28.0, "basis": "prior"},
            "carry": {"recommended_pct": 20.0, "basis": "prior"},
            "earnings": {"recommended_pct": 12.0, "basis": "prior"},
            "momentum": {"recommended_pct": 25.0, "basis": "prior"}}


# trend default budget pct is 28.0 (vrp/earnings are defunded to 0.0, so mechanism tests use trend, which
# has room to move both ways). A measured rec of 23.0 -> wants -5, capped to -2 (MAX_STEP) -> 26.0.
def _trend_rec(recommended_pct, basis="measured_proven"):
    return {"trend": {"recommended_pct": recommended_pct, "basis": basis},
            "vrp": {"recommended_pct": 0.0, "basis": "prior"},
            "carry": {"recommended_pct": 20.0, "basis": "prior"},
            "earnings": {"recommended_pct": 0.0, "basis": "prior"},
            "momentum": {"recommended_pct": 25.0, "basis": "prior"}}


def test_disabled_is_noop_but_plan_shows_moves(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _trend_rec(23.0))
    _enable(monkeypatch, False)
    res = A().apply()
    assert res["applied"] is False and res["status"] == "AUTOAPPLY_DISABLED"
    # but the plan still computes the capped move for transparency
    plan = A().plan()
    m = [x for x in plan["moves"] if x["sleeve"] == "trend"][0]
    assert m["from_pct"] == 28.0 and m["to_pct"] == 26.0 and m["step_pct"] == -2.0    # capped at MAX_STEP


def test_apply_writes_capped_override_and_pct_honors_it(monkeypatch, tmp_path):
    ov = _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _trend_rec(23.0))
    _enable(monkeypatch, True)
    res = A().apply()
    assert res["applied"] is True and res["status"] == "AUTOAPPLY_APPLIED"
    assert json.loads(ov.read_text())["pct"]["trend"] == 26.0
    # the budget engine now resolves trend to the override, not the 28.0 default
    monkeypatch.delenv("GREYLINE_TREND_ALLOC_PCT", raising=False)
    assert B.pct("trend") == 26.0


def test_static_prior_sleeve_is_never_moved(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    # trend recommendation differs a lot but basis is a static prior -> must be skipped
    _rec(monkeypatch, _trend_rec(5.0, basis="prior"))
    _enable(monkeypatch, True)
    res = A().apply()
    assert res["status"] == "AUTOAPPLY_NO_MOVES" and res["applied"] is False


def test_deadband_skips_tiny_moves(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _trend_rec(27.7))   # 28.0 -> 27.7 = -0.3, below MIN_MOVE_PCT 0.5
    _enable(monkeypatch, True)
    assert A().apply()["status"] == "AUTOAPPLY_NO_MOVES"


def test_env_pin_always_wins_over_override(monkeypatch, tmp_path):
    ov = _point_files(monkeypatch, tmp_path)
    ov.write_text(json.dumps({"pct": {"trend": 26.0}}))
    monkeypatch.setenv("GREYLINE_TREND_ALLOC_PCT", "18")   # explicit operator pin
    assert B.pct("trend") == 18.0                          # env beats the override


def test_revert_clears_overrides(monkeypatch, tmp_path):
    ov = _point_files(monkeypatch, tmp_path)
    ov.write_text(json.dumps({"pct": {"trend": 26.0}}))
    monkeypatch.delenv("GREYLINE_TREND_ALLOC_PCT", raising=False)
    assert B.pct("trend") == 26.0
    res = A().revert()
    assert res["reverted"] is True and not ov.exists()
    assert B.pct("trend") == 28.0                          # back to the default


def test_cumulative_stepping_across_applies(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _trend_rec(23.0))
    _enable(monkeypatch, True)
    A().apply()                                            # 28 -> 26
    monkeypatch.delenv("GREYLINE_TREND_ALLOC_PCT", raising=False)
    assert B.pct("trend") == 26.0
    A().apply()                                            # 26 -> 24 (another capped step)
    assert B.pct("trend") == 24.0


def test_run_if_due_deferred_when_market_open(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _vrp_rec(10.0))
    _enable(monkeypatch, True)
    res = A().run_if_due(market_open=True)
    assert res["ran"] is False and res["status"] == "AUTOAPPLY_DEFERRED_MARKET_OPEN"


def test_run_if_due_once_per_day(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _vrp_rec(10.0))
    _enable(monkeypatch, True)
    first = A().run_if_due(market_open=False)
    assert first["ran"] is True and first["applied"] is True
    second = A().run_if_due(market_open=False)
    assert second["ran"] is False and second["status"] == "AUTOAPPLY_ALREADY_RAN_TODAY"


def test_force_applies_even_when_disabled(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _vrp_rec(10.0))
    _enable(monkeypatch, False)
    res = A().apply(force=True)                            # deliberate operator apply via the route
    assert res["applied"] is True and res["status"] == "AUTOAPPLY_APPLIED"
    assert res["source"] == "operator_forced"


# ---- plan-bound operator approval ------------------------------------------------------------------

def test_plan_token_present_and_deterministic(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _vrp_rec(10.0))
    _enable(monkeypatch, False)
    t1 = A().plan()["plan_token"]
    t2 = A().plan()["plan_token"]
    assert t1 and t1 == t2                                 # stable given the same evidence
    assert A().status()["plan_preview"]["plan_token"] == t1   # surfaced for the operator to echo back


def test_matching_token_approves_apply_even_when_disabled(monkeypatch, tmp_path):
    ov = _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _trend_rec(23.0))
    _enable(monkeypatch, False)                            # auto-apply OFF
    token = A().plan()["plan_token"]
    res = A().apply(plan_token=token)                      # operator approves THIS exact plan
    assert res["applied"] is True and res["status"] == "AUTOAPPLY_APPLIED"
    assert res["source"] == "operator_approved" and res["plan_token"] == token
    assert json.loads(ov.read_text())["pct"]["trend"] == 26.0
    # provenance recorded for the ALLOC_OVERRIDE_COHERENT guard
    hist = [json.loads(l) for l in (tmp_path / "hist.jsonl").read_text().splitlines() if l.strip()]
    assert hist[-1]["source"] == "operator_approved" and hist[-1]["plan_token"] == token


def test_mismatched_token_refuses_and_writes_nothing(monkeypatch, tmp_path):
    ov = _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _vrp_rec(10.0))
    _enable(monkeypatch, False)
    res = A().apply(plan_token="staletoken00")             # approving a plan that no longer matches
    assert res["applied"] is False and res["status"] == "AUTOAPPLY_PLAN_CHANGED"
    assert res["current_token"] and res["reviewed_token"] == "staletoken00"
    assert not ov.exists()                                 # nothing applied — exactly the reviewed plan or none


def test_token_changes_when_the_plan_changes(monkeypatch, tmp_path):
    _point_files(monkeypatch, tmp_path)
    _rec(monkeypatch, _trend_rec(23.0))                    # trend 28 -> 26.0 (capped)
    _enable(monkeypatch, False)
    token_old = A().plan()["plan_token"]
    _rec(monkeypatch, _trend_rec(30.0))                    # evidence shifts: trend -> 30.0 (different result)
    token_new = A().plan()["plan_token"]
    assert token_old != token_new
    # approving with the STALE token is refused under the new plan
    assert A().apply(plan_token=token_old)["status"] == "AUTOAPPLY_PLAN_CHANGED"
