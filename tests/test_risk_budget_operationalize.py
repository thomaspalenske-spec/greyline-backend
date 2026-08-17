"""Operationalizing the risk-budget backtest: the gated, floored, DOWN-only risk-parity de-concentration.
Verifies the safety rails — gated OFF by default, pin is a ceiling (trim only pulls DOWN), diversifier
floor, capped step glide. Reads the real historical CSVs (advisory vols), so the module is exempt from the
app/data wipe. No orders, no network."""

import json

import pytest

from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as BUD
from app.services.sleeve_budget_autoapply_engine import SleeveBudgetAutoApplyEngine as AA


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Pin the four armed sleeves (so the advisory populates) and point BOTH engines' override file at a tmp
    path so tests never touch the real override."""
    of = tmp_path / "override.json"
    monkeypatch.setattr(BUD, "OVERRIDE_FILE", of)
    monkeypatch.setattr(AA, "OVERRIDE_FILE", of)
    for s, pct in (("TREND", "28"), ("VOL_CARRY", "20"), ("LOW_VOL", "12"), ("XS_MOMENTUM", "12")):
        monkeypatch.setenv("GREYLINE_%s_ALLOC_PCT" % s, pct)
    monkeypatch.delenv("GREYLINE_SLEEVE_RISK_BUDGET", raising=False)
    return of


def _write_risk_trim(path, trim):
    path.write_text(json.dumps({"pct": {}, "risk_trim": trim}))


# ---- floor ----

def test_vol_carry_has_a_diversifier_floor(env, monkeypatch):
    assert BUD._risk_floor("vol_carry") == 5.0
    monkeypatch.setenv("GREYLINE_VOL_CARRY_RISK_FLOOR_PCT", "8")
    assert BUD._risk_floor("vol_carry") == 8.0
    assert BUD._risk_floor("trend") == 0.0


# ---- pct() gating + pin reconciliation ----

def test_gated_off_pin_wins_even_with_risk_trim(env):
    _write_risk_trim(env, {"vol_carry": 8.0})
    # flag OFF -> the pin (20) stands; the risk_trim is ignored entirely
    assert BUD.pct("vol_carry") == 20.0

def test_gated_on_trim_pulls_pinned_sleeve_down(env, monkeypatch):
    _write_risk_trim(env, {"vol_carry": 8.0})
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    assert BUD.pct("vol_carry") == 8.0            # pin reconciliation: trimmed DOWN toward risk-parity

def test_gated_on_trim_never_raises_above_pin(env, monkeypatch):
    _write_risk_trim(env, {"vol_carry": 30.0})   # above the 20 pin
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    assert BUD.pct("vol_carry") == 20.0          # pin is the CEILING — a trim never lifts it


# ---- glide plan: down-only, capped, floored ----

def test_risk_trim_plan_inactive_when_gated_off(env):
    # plan() is a read-only PREVIEW (may show moves even when gated off); `active` is the live gate, and
    # apply is what actually refuses when off (covered by test_apply_gated_off_no_write).
    p = AA().risk_trim_plan()
    assert p["active"] is False

def test_risk_trim_plan_steps_vol_carry_down_capped(env, monkeypatch):
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    p = AA().risk_trim_plan()
    assert p["active"] is True
    vc = next((m for m in p["moves"] if m["sleeve"] == "vol_carry"), None)
    assert vc is not None
    assert vc["step_pct"] < 0                                  # DOWN only
    assert abs(vc["step_pct"]) <= AA.MAX_STEP_PCT + 1e-9       # capped per apply
    assert vc["to_pct"] < vc["from_pct"]
    assert vc["target_pct"] >= BUD._risk_floor("vol_carry")    # floored


# ---- apply gating + glide + reversibility ----

def test_apply_gated_off_no_write(env):
    res = AA().apply_risk_trim()                  # flag off, no force
    assert res["applied"] is False and res["status"] == "RISK_TRIM_DISABLED"
    assert not env.exists()

def test_apply_force_writes_and_preserves_pct(env, monkeypatch):
    env.write_text(json.dumps({"pct": {"momentum": 9.0}}))     # a pre-existing allocator override
    res = AA().apply_risk_trim(force=True)
    assert res["applied"] is True
    d = json.loads(env.read_text())
    assert "vol_carry" in d["risk_trim"]
    assert d["pct"] == {"momentum": 9.0}          # allocator override preserved

def test_glide_steps_down_over_successive_applies(env, monkeypatch):
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    aa = AA()
    r1 = aa.apply_risk_trim()
    v1 = json.loads(env.read_text())["risk_trim"]["vol_carry"]
    assert v1 == round(20.0 - AA.MAX_STEP_PCT, 2)              # first step down from the pin
    r2 = aa.apply_risk_trim()
    v2 = json.loads(env.read_text())["risk_trim"]["vol_carry"]
    assert v2 < v1                                             # glides further down
    # and pct() honors the latest trim under the flag
    assert BUD.pct("vol_carry") == v2

def test_run_risk_trim_deferred_when_market_open(env, monkeypatch):
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    assert AA().run_risk_trim_if_due(market_open=True)["status"] == "RISK_TRIM_DEFERRED_MARKET_OPEN"

def test_revert_clears_risk_trim(env, monkeypatch):
    monkeypatch.setenv("GREYLINE_SLEEVE_RISK_BUDGET", "true")
    AA().apply_risk_trim()
    assert env.exists()
    AA().revert()
    assert not env.exists()
    monkeypatch.delenv("GREYLINE_SLEEVE_RISK_BUDGET", raising=False)
    assert BUD.pct("vol_carry") == 20.0           # back to the pin
