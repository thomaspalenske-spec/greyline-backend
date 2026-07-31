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
