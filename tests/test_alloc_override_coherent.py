"""Reality Guard invariant ALLOC_OVERRIDE_COHERENT — the gated budget auto-apply writes reversible sleeve
%-overrides; this asserts they can't silently drift into an incoherent state: sane pct, book <= 100% of
equity, and every override traces to a real recorded apply (no orphan/manual injection). No file = clean."""

import json

from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine as B
from app.services.sleeve_budget_autoapply_engine import SleeveBudgetAutoApplyEngine as A


def _files(monkeypatch, tmp_path, overrides=None, history_moves="__default__"):
    """The check reads the override + history paths straight off the engine constants — point those at
    tmp files so there's one source of truth and no chdir games."""
    ov = tmp_path / "sleeve_pct_overrides.json"
    hist = tmp_path / "sleeve_pct_autoapply_history.jsonl"
    if overrides is not None:
        ov.write_text(json.dumps({"applied_at": "t", "source": "auto_apply", "pct": overrides}))
    if history_moves == "__default__" and overrides is not None:
        history_moves = [{"sleeve": s} for s in overrides]     # by default, every override has a trace
    if history_moves not in (None, "__default__"):
        hist.write_text(json.dumps({"moves": history_moves}) + "\n")
    monkeypatch.setattr(B, "OVERRIDE_FILE", ov)                # B.pct() + the check read this
    monkeypatch.setattr(A, "HISTORY", hist)                    # the check reads provenance from this
    # clear real env pins so the budget total is deterministic (defaults sum to 100)
    for k in ("MOMENTUM", "TREND", "VOL_CARRY", "VRP", "EARNINGS", "MANAGED_FUTURES"):
        monkeypatch.delenv("GREYLINE_%s_ALLOC_PCT" % k, raising=False)
    return ov, hist


def test_no_override_file_is_clean(monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path, overrides=None)
    r = G()._check_alloc_override_coherent()
    assert r["ok"] is True and "no auto-apply sleeve overrides" in r["detail"]


def test_coherent_overrides_pass(monkeypatch, tmp_path):
    # trend 28->24, momentum 25->22 (moved DOWN so the book stays <= 100 under the live sleeve set);
    # both have a recorded apply. (Not the exact total — that shifts as the default sleeve set evolves.)
    _files(monkeypatch, tmp_path, overrides={"trend": 24.0, "momentum": 22.0})
    r = G()._check_alloc_override_coherent()
    assert r["ok"] is True and "coherent" in r["detail"]


def test_out_of_range_pct_flags(monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path, overrides={"vrp": 130.0})
    r = G()._check_alloc_override_coherent()
    assert r["ok"] is False and "out of [0,100]" in r["detail"]


def test_book_over_100_flags(monkeypatch, tmp_path):
    # push several sleeves up so the effective book sum exceeds 100%
    _files(monkeypatch, tmp_path, overrides={"vrp": 40.0, "earnings": 30.0})   # 25+28+20+40+30 = 143
    r = G()._check_alloc_override_coherent()
    assert r["ok"] is False and "> 100% of equity" in r["detail"]


def test_orphan_override_without_recorded_apply_flags(monkeypatch, tmp_path):
    # override present but the history log records a move for a DIFFERENT sleeve only -> orphan
    _files(monkeypatch, tmp_path, overrides={"vrp": 13.0}, history_moves=[{"sleeve": "trend"}])
    r = G()._check_alloc_override_coherent()
    assert r["ok"] is False and "orphan/manual" in r["detail"] and "vrp" in r["detail"]


def test_missing_history_is_unverified(monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path, overrides={"vrp": 13.0}, history_moves=None)  # no history file
    r = G()._check_alloc_override_coherent()
    assert r["ok"] is False and "provenance UNVERIFIED" in r["detail"]


def test_env_pin_shadow_is_noted_not_failed(monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path, overrides={"trend": 24.0})
    monkeypatch.setenv("GREYLINE_TREND_ALLOC_PCT", "24")   # env pin shadows the override; keeps book <=100
    r = G()._check_alloc_override_coherent()
    assert r["ok"] is True and "shadowed by an env pin" in r["detail"]


def test_registered_in_check(monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path, overrides=None)
    ids = [c["id"] for c in G().check()["checks"]]
    assert "ALLOC_OVERRIDE_COHERENT" in ids
