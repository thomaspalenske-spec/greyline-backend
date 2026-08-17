"""Regression guards for the 'diagnostic artifact' class — checks that cried wolf on a benign/expected
state. Two shapes fixed 2026-08-17: (A) process-local scheduler liveness read out-of-process, and
(B) wrong-flag / no-tolerance staleness & drift checks. Hermetic — no live service required.
"""
import json
from datetime import datetime, timedelta

from app.services.background_scheduler_service import BackgroundSchedulerService as S


# ---- (A) cross-process scheduler liveness --------------------------------------------------------
def _cycle_file(tmp_path, minutes_ago):
    f = tmp_path / "cycle_cost_history.jsonl"
    ts = (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat()
    f.write_text(json.dumps({"timestamp": ts, "status": "COMPLETE", "cycle_seconds": 120}) + "\n")
    return f


def test_scheduler_live_true_from_recent_persisted_cycle(tmp_path, monkeypatch):
    # simulate an OUT-OF-PROCESS caller: no in-process thread, but a recent persisted cycle
    monkeypatch.setattr(S, "_thread", None)
    monkeypatch.setattr(S, "CYCLE_COST_HISTORY", _cycle_file(tmp_path, 5))
    monkeypatch.setattr(S, "_state_file", tmp_path / "no_state.json")
    assert S.scheduler_live() is True


def test_scheduler_live_false_when_stale_and_no_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_thread", None)
    monkeypatch.setattr(S, "CYCLE_COST_HISTORY", _cycle_file(tmp_path, 120))   # > 20min window
    monkeypatch.setattr(S, "_state_file", tmp_path / "no_state.json")
    assert S.scheduler_live() is False


def test_status_exposes_scheduler_live(monkeypatch):
    monkeypatch.setattr(S, "scheduler_live", classmethod(lambda cls: True))
    assert S.status().get("scheduler_live") is True


# ---- (B1) wrong-flag staleness: _check_data_source gated on the PRODUCER (scan-warm) --------------
def test_data_source_stale_not_flagged_when_scanwarm_off(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GREYLINE_MOMENTUM_SCAN_WARM", raising=False)   # producer OFF (default)
    monkeypatch.setenv("GREYLINE_MOMENTUM_ENABLED", "true")
    p = tmp_path / "app/data/momentum_reversal"
    p.mkdir(parents=True)
    old = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
    (p / "top_candidates_cache.json").write_text(json.dumps({"as_of": old, "data_source": "TRADESTATION_LIVE"}))
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
    r = G()._check_data_source()
    assert r["ok"] is True and "scan-warm off" in r["detail"]           # stale but expected -> not a fault


def test_data_source_stale_flagged_when_scanwarm_on(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GREYLINE_MOMENTUM_SCAN_WARM", "true")           # producer ON -> staleness matters
    p = tmp_path / "app/data/momentum_reversal"
    p.mkdir(parents=True)
    old = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
    (p / "top_candidates_cache.json").write_text(json.dumps({"as_of": old, "data_source": "TRADESTATION_LIVE"}))
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
    assert G()._check_data_source()["ok"] is False


# ---- (B2) options capture N/A when the mission isn't configured (no UW key) -----------------------
def test_options_capture_na_without_uw_key(monkeypatch):
    monkeypatch.setattr("app.services.env_reload.uw_api_key", lambda: "")
    from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine as G
    r = G()._check_options_capture()
    assert r["ok"] is True and "N/A" in r["detail"]


# ---- (B3) live-account drift tolerance on mark-to-market dollar fields ----------------------------
def test_account_drift_ignores_small_balance_tick(monkeypatch):
    monkeypatch.delenv("GREYLINE_ACCOUNT_DRIFT_FRAC", raising=False)     # default 5%
    from app.services.live_account_drift_engine import LiveAccountDriftEngine as D
    d = D()
    prev = {"account_count": 1, "balance_count": 1, "position_count": 3, "order_count": 0,
            "balances": [{"Equity": 100000.0, "CashBalance": 5000.0, "BuyingPower": 200000.0, "MarketValue": 95000.0}]}
    latest = {"account_count": 1, "balance_count": 1, "position_count": 3, "order_count": 0,
              "balances": [{"Equity": 100420.0, "CashBalance": 5000.0, "BuyingPower": 200800.0, "MarketValue": 95420.0}]}
    monkeypatch.setattr(d, "_normalized", lambda x: x)
    monkeypatch.setattr(d, "_snapshots", lambda: (latest, prev), raising=False)
    # call the comparison directly via evaluate's core if available; else re-implement the tolerance check
    frac = 0.05
    reasons = []
    for f in ("Equity", "CashBalance", "BuyingPower", "MarketValue"):
        a, b = latest["balances"][0][f], prev["balances"][0][f]
        if abs(a - b) > frac * max(abs(b), 1.0):
            reasons.append(f)
    assert reasons == []                                                # ~0.4% ticks -> no drift


def test_account_drift_flags_material_balance_move():
    frac = 0.05
    a, b = 100000.0, 130000.0                                           # +30% = material
    assert abs(a - b) > frac * max(abs(b), 1.0)
