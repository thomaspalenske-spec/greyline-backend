"""Condor shadow forward-test: open/dedupe, mid-mark, profit-take close, report. No live UW."""

import json

import pytest

from app.services.condor_shadow_engine import CondorShadowEngine as C

_FAKE = {
    "symbol": "AAA", "expiration": "2099-09-18", "quantity": 1, "_sleeve": "vrp",
    "credit_per_condor": 0.20, "max_loss_total": 80.0, "iv_rank": 0.9,
    "legs": {
        "short_call": {"symbol": "AAA 990918C110", "strike": 110, "bid": 1.0, "ask": 1.1},
        "wing_call":  {"symbol": "AAA 990918C112", "strike": 112, "bid": 0.5, "ask": 0.6},
        "short_put":  {"symbol": "AAA 990918P90",  "strike": 90,  "bid": 1.0, "ask": 1.1},
        "wing_put":   {"symbol": "AAA 990918P88",  "strike": 88,  "bid": 0.5, "ask": 0.6},
    },
}  # entry mid = (1.05+1.05) - (0.55+0.55) = 1.00


@pytest.fixture(autouse=True)
def _tmp(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.condor_shadow_engine.STATE", tmp_path)
    monkeypatch.setattr("app.services.condor_shadow_engine.LEDGER", tmp_path / "l.jsonl")
    monkeypatch.setenv("GREYLINE_CONDOR_SHADOW", "true")
    yield


def test_open_records_entry_mid_and_dedupes(monkeypatch):
    monkeypatch.setattr(C, "_candidate_condors", lambda self: ([dict(_FAKE)], {}))
    e = C()
    assert len(e.open_new()) == 1
    row = json.loads((e._entries())[0] and json.dumps(e._entries()[0]))
    assert row["status"] == "OPEN"
    assert row["entry_credit_mid"] == pytest.approx(1.0)     # mid, not the marketable credit
    assert len(e.open_new()) == 0                            # same symbol+expiry -> no duplicate


def test_day0_unrealized_is_zero_at_mid(monkeypatch):
    monkeypatch.setattr(C, "_candidate_condors", lambda self: ([dict(_FAKE)], {}))
    # current quotes == entry quotes -> current mid == entry mid -> ~0 unrealized
    monkeypatch.setattr(C, "_current_value", lambda self, legs: 1.0)
    e = C(); e.open_new()
    assert e.report()["unrealized_pnl"] == pytest.approx(0.0)


def test_mark_closes_on_profit_take(monkeypatch):
    monkeypatch.setattr(C, "_candidate_condors", lambda self: ([dict(_FAKE)], {}))
    e = C(); e.open_new()
    # condor value decayed to 0.40 (<= 50% of the 1.00 entry) -> take profit
    monkeypatch.setattr(C, "_current_value", lambda self, legs: 0.40)
    closed = e.mark()
    assert len(closed) == 1
    row = e._entries()[0]
    assert row["status"] == "CLOSED" and row["close_reason"] == "profit_take"
    assert row["realized_pnl"] == pytest.approx((1.0 - 0.40) * 100)   # $60


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_CONDOR_SHADOW", "false")
    assert C().run_if_due()["status"] == "CONDOR_SHADOW_DISABLED"


def test_report_shape(monkeypatch):
    monkeypatch.setattr(C, "_candidate_condors", lambda self: ([dict(_FAKE)], {}))
    monkeypatch.setattr(C, "_current_value", lambda self, legs: 1.0)
    e = C(); e.open_new()
    r = e.report()
    assert r["open_condors"] == 1 and r["closed_condors"] == 0
    assert r["status"] == "CONDOR_SHADOW_ACCUMULATING"


def test_report_splits_verdict_by_sleeve(monkeypatch):
    # earnings-vol must be measurable SEPARATELY from VRP (the whole point of two forward-tests).
    e = C()
    rows = [
        {"status": "CLOSED", "sleeve": "vrp", "realized_pnl": 275.0},
        {"status": "CLOSED", "sleeve": "vrp", "realized_pnl": -100.0},
        {"status": "CLOSED", "sleeve": "earnings", "realized_pnl": 50.0},
        {"status": "OPEN", "sleeve": "earnings", "legs": {}, "quantity": 1, "entry_credit_mid": 0.5},
    ]
    from app.services import condor_shadow_engine as mod
    mod.LEDGER.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    rep = e.report()
    bs = rep["by_sleeve"]
    assert bs["vrp"]["closed_condors"] == 2 and bs["vrp"]["realized_pnl"] == pytest.approx(175.0)
    assert bs["vrp"]["win_rate_pct"] == pytest.approx(50.0)
    assert bs["earnings"]["closed_condors"] == 1 and bs["earnings"]["open_condors"] == 1
    assert bs["earnings"]["win_rate_pct"] == pytest.approx(100.0)


_EXP_LEGS = {"short_call": {"strike": 110}, "wing_call": {"strike": 115},
             "short_put": {"strike": 90}, "wing_put": {"strike": 85}}


def test_intrinsic_close_value_at_expiry():
    assert C._intrinsic_close_value(_EXP_LEGS, 100.0) == 0.0    # between shorts -> worthless, full credit kept
    assert C._intrinsic_close_value(_EXP_LEGS, 112.0) == 2.0    # call ITM by 2
    assert C._intrinsic_close_value(_EXP_LEGS, 120.0) == 5.0    # capped at the 5-wide wing (max loss)
    assert C._intrinsic_close_value(_EXP_LEGS, 88.0) == 2.0     # put ITM by 2


def test_mark_settles_expiring_unquotable_condor(monkeypatch, tmp_path):
    """A 0-DTE condor UW can't quote must SETTLE at intrinsic — not hang OPEN forever (the CLX/OKE/LDOS case)."""
    e = {"id": "X", "symbol": "XYZ", "expiration": "2020-01-01", "sleeve": "earnings",
         "entry_credit_mid": 1.00, "quantity": 1, "status": "OPEN", "legs": _EXP_LEGS}
    (tmp_path / "l.jsonl").write_text(json.dumps(e) + "\n")
    monkeypatch.setattr(C, "_current_value", lambda self, legs: None)     # UW no offer on the expiring legs
    monkeypatch.setattr(C, "_underlying_spot", lambda self, sym: 100.0)   # settles between the shorts -> worthless
    assert C().mark() == ["X"]
    r = [json.loads(l) for l in (tmp_path / "l.jsonl").read_text().splitlines() if l.strip()][0]
    assert r["status"] == "CLOSED" and r["close_reason"] == "expiry_settle"
    assert r["close_value_per"] == 0.0 and r["realized_pnl"] == 100.0     # (1.00 - 0) * 100 * 1 = full credit


def test_mark_settles_breached_condor_at_max_loss(monkeypatch, tmp_path):
    e = {"id": "Z", "symbol": "XYZ", "expiration": "2020-01-01", "sleeve": "earnings",
         "entry_credit_mid": 1.00, "quantity": 1, "status": "OPEN", "legs": _EXP_LEGS}
    (tmp_path / "l.jsonl").write_text(json.dumps(e) + "\n")
    monkeypatch.setattr(C, "_current_value", lambda self, legs: None)
    monkeypatch.setattr(C, "_underlying_spot", lambda self, sym: 130.0)   # blew through the call wing -> max loss
    C().mark()
    r = [json.loads(l) for l in (tmp_path / "l.jsonl").read_text().splitlines() if l.strip()][0]
    assert r["close_value_per"] == 5.0 and r["realized_pnl"] == -400.0    # (1.00 - 5.0) * 100 = -400


def test_mark_leaves_nonexpiring_unquotable_condor_open(monkeypatch, tmp_path):
    """A transiently-unquotable but NOT expiring condor is left OPEN to retry — only expiry forces a settle."""
    e = {"id": "Y", "symbol": "XYZ", "expiration": "2099-09-18", "sleeve": "vrp",
         "entry_credit_mid": 1.00, "quantity": 1, "status": "OPEN", "legs": _EXP_LEGS}
    (tmp_path / "l.jsonl").write_text(json.dumps(e) + "\n")
    monkeypatch.setattr(C, "_current_value", lambda self, legs: None)
    assert C().mark() == []
    r = [json.loads(l) for l in (tmp_path / "l.jsonl").read_text().splitlines() if l.strip()][0]
    assert r["status"] == "OPEN"


def test_spot_on_returns_close_on_or_before_date(tmp_path, monkeypatch):
    import app.services.condor_shadow_engine as csm
    monkeypatch.setattr(csm, "BARS", tmp_path)
    (tmp_path / "ZZ_daily.csv").write_text(
        "date,open,high,low,close,volume\n2026-08-19,1,1,1,50,1\n2026-08-20,1,1,1,55,1\n2026-08-21,1,1,1,60,1\n")
    assert C()._spot_on("ZZ", "2026-08-20") == 55.0     # the close ON the date
    assert C()._spot_on("ZZ", "2026-08-25") == 60.0     # nearest bar on/before -> the last one
    assert C()._spot_on("ZZ", "2026-08-18") is None     # no bar on/before


def test_settle_expired_runs_even_when_market_closed(tmp_path, monkeypatch):
    """RESILIENCE: an expired condor settles even when the market is CLOSED and the daily marker is set — so a
    missed cycle (weekend, power loss) can't leave it dangling (the 2026-08-25 stuck-4-days-past-expiry bug)."""
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: False)
    e = {"id": "X", "symbol": "XYZ", "expiration": "2020-01-01", "sleeve": "earnings",
         "entry_credit_mid": 1.00, "quantity": 1, "status": "OPEN", "legs": _EXP_LEGS}
    (tmp_path / "l.jsonl").write_text(json.dumps(e) + "\n")           # autouse _tmp fixture points LEDGER here
    (tmp_path / "last_run.txt").write_text("2020-01-01")             # marker set -> normal path would NOT run
    monkeypatch.setattr(C, "_current_value", lambda self, legs: None)
    monkeypatch.setattr(C, "_spot_on", lambda self, sym, on: 100.0)  # between the shorts -> worthless
    r = C().run_if_due()
    assert r["status"] == "CONDOR_SHADOW_MARKET_CLOSED" and r["expired_settled"] == 1
    rec = [json.loads(l) for l in (tmp_path / "l.jsonl").read_text().splitlines() if l.strip()][0]
    assert rec["status"] == "CLOSED" and rec["close_reason"] == "expiry_settle" and rec["realized_pnl"] == 100.0
