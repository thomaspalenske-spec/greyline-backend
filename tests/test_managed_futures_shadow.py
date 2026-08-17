"""MF shadow forward-test: mark cadence, return math, report gating. Real bars, temp ledger, no broker."""

import json
from pathlib import Path

import pytest

from app.services.managed_futures_shadow_engine import ManagedFuturesShadowEngine as S

_REAL_HIST = Path(__file__).resolve().parents[1] / "app" / "data" / "historical"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "HIST", _REAL_HIST)          # real bars for the signal
    monkeypatch.setattr(S, "STATE", tmp_path)           # temp ledger — never touch the real one
    monkeypatch.setattr(S, "LEDGER", tmp_path / "shadow_ledger.jsonl")
    monkeypatch.setenv("GREYLINE_MANAGED_FUTURES_SHADOW", "true")
    yield


def _seed(entries):
    S.LEDGER.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def test_disabled(monkeypatch):
    monkeypatch.setenv("GREYLINE_MANAGED_FUTURES_SHADOW", "false")
    assert S().mark()["status"] == "SHADOW_DISABLED"


def test_first_mark_creates_entry():
    r = S().mark()
    assert r["status"] == "SHADOW_MARKED" and r["acted"] is True
    assert r["rebalanced"] is True and r["daily_return"] is None      # no prior bar to book
    assert S.LEDGER.exists()


def test_mark_idempotent_same_bar():
    S().mark()
    assert S().mark()["status"] == "SHADOW_NO_NEW_BAR"                # no new settled bar -> no double-count


def test_full_long_short_weights_include_shorts():
    have, common, px = S()._aligned()
    w = S()._target_weights(have, px, len(common) - 1)
    assert any(v > 0 for v in w.values()) and any(v < 0 for v in w.values())  # the SHORT side exists


def test_mark_books_return_from_prior():
    # seed a prior bar dated in the past with known closes/weights -> next mark computes a real return
    prior = {"date": "2020-01-02", "month": "2020-01",
             "weights": {s: 0.1 for s in S.BASKET}, "closes": {s: 50.0 for s in S.BASKET}}
    _seed([prior])
    r = S().mark()
    assert r["status"] == "SHADOW_MARKED"
    assert isinstance(r["daily_return"], float)                       # booked P&L of the prior weights


def test_report_accumulating():
    _seed([{"date": f"2026-07-{10+i:02d}", "month": "2026-07",
            "weights": {}, "closes": {}, "daily_return": 0.001 * (i - 1)} for i in range(3)])
    rep = S().report()
    assert rep["status"] == "SHADOW_ACCUMULATING" and rep["days_tracked"] == 3
    assert "cumulative_return_pct" in rep


def test_report_measuring_after_min_days():
    _seed([{"date": f"2026-06-{1+i:02d}", "month": "2026-06",
            "weights": {}, "closes": {}, "daily_return": 0.002} for i in range(S.MIN_DAYS + 1)])
    rep = S().report()
    assert rep["status"] == "SHADOW_MEASURING"
    assert rep["annualized_sharpe"] is not None
    assert "vs backtest" in rep["verdict"]
