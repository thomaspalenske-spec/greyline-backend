"""Overnight-anomaly shadow: overnight return = open_t / close_{t-1} - 1, equal-weight; cost sweep;
forward-only idempotent accrual; report shape. Deterministic tmp bars — no network, no orders."""

import pytest

import app.services.overnight_anomaly_shadow_engine as osm
from app.services.overnight_anomaly_shadow_engine import OvernightAnomalyShadowEngine as O


@pytest.fixture
def bars(tmp_path, monkeypatch):
    monkeypatch.setattr(osm, "BARS", tmp_path)
    monkeypatch.setattr(O, "LEDGER", tmp_path / "led.jsonl")
    monkeypatch.setenv("GREYLINE_OVERNIGHT_UNIVERSE", "FOO")
    monkeypatch.setenv("GREYLINE_OVERNIGHT_COST_BPS", "2")
    (tmp_path / "FOO_daily.csv").write_text(
        "date,open,high,low,close,volume\n"
        "2026-01-02,100,100,100,100,1\n"
        "2026-01-03,102,102,102,101,1\n"     # overnight = 102/100 - 1 = 0.02
        "2026-01-04,100,100,100,100,1\n")    # overnight = 100/101 - 1 ~ -0.009901
    return tmp_path


def test_overnight_return_is_open_over_prior_close(bars):
    by = O._overnight_by_date(["FOO"])
    assert abs(by["2026-01-03"] - 0.02) < 1e-9
    assert abs(by["2026-01-04"] - (100 / 101 - 1)) < 1e-9
    assert "2026-01-02" not in by                 # first day has no prior close


def test_nonpositive_price_bar_skipped(bars, tmp_path):
    (tmp_path / "BAR_daily.csv").write_text(
        "date,open,high,low,close,volume\n2026-01-02,0,0,0,0,1\n2026-01-03,10,10,10,10,1\n")
    assert O._open_close("BAR") == [("2026-01-03", 10.0, 10.0)]


def test_run_if_due_forward_only_and_idempotent(bars):
    r1 = O().run_if_due()
    # first deploy records ONLY the latest obs (start point) — it does NOT backfill history
    assert r1["ran"] is True and r1["observations_added"] == 1
    import json
    rows = [json.loads(l) for l in (bars / "led.jsonl").read_text().splitlines() if l.strip()]
    assert [r["date"] for r in rows] == ["2026-01-04"]     # the latest, not 01-03
    r2 = O().run_if_due()                          # nothing newer than the last recorded
    assert r2["observations_added"] == 0


def test_report_forward_count_after_first_deploy(bars):
    O().run_if_due()
    assert O().report()["forward_shadow"]["n"] == 1        # exactly the one forward obs, not the history


def test_cost_sweep_subtracts_round_trip(bars):
    sweep = O()._cost_sweep([0.0004, 0.0004])      # 4 bps gross both days
    at4 = next(c for c in sweep if c["cost_bps"] == 4)
    assert abs(at4["net_mean_bps_per_day"]) < 1e-6  # net zero at 4 bps


def test_report_structure(bars):
    O().run_if_due()
    r = O().report()
    assert r["status"] == "OVERNIGHT_ANOMALY_SHADOW"
    assert r["universe"]["names"] == ["FOO"]
    assert "forward_shadow" in r and "historical_context" in r
    assert r["forward_shadow"]["n"] <= 2           # only the 2 forward obs
    assert "FORWARD_SHADOW" in r["forward_shadow"]["track"]


def test_disabled_flag_is_a_noop(bars, monkeypatch):
    monkeypatch.setenv("GREYLINE_OVERNIGHT_SHADOW", "false")
    assert O().run_if_due() == {"status": "OVERNIGHT_SHADOW_DISABLED", "ran": False}
