"""Momentum-reversal EQUITY shadow: cohort open/settle cadence, net return math, non-overlap, report
gating. Fully isolated state + stubbed signal/bars — no network, no broker, no real ledger touched."""

import json

import pytest

from app.services.momentum_reversal_shadow_engine import MomentumReversalShadowEngine as M


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "STATE", tmp_path)
    monkeypatch.setattr(M, "OPEN", tmp_path / "open.json")
    monkeypatch.setattr(M, "CLOSED", tmp_path / "closed.jsonl")
    monkeypatch.setattr(M, "BENCH_CACHE", tmp_path / "top_candidates_cache.json")
    monkeypatch.setenv("GREYLINE_MOMENTUM_EQUITY_SHADOW", "true")
    monkeypatch.setenv("GREYLINE_COST_BPS_ROUND_TRIP", "10")   # 10bps round-trip
    yield


def _stub_signal(monkeypatch, picks, asof="2026-08-10"):
    # (top_n targets, full clean bench, as_of, top_n) — bench == picks for the tests
    monkeypatch.setattr(M, "_signal_targets",
                        lambda self: ([dict(p) for p in picks], [dict(p) for p in picks], asof, len(picks)))


def _stub_bars(monkeypatch, bars):
    # bars: {symbol: [closes...]} — index-addressable exactly like the real settled CSV
    monkeypatch.setattr(M, "_closes", lambda self, sym, _b=bars: list(_b.get(sym, [])))


def test_disabled(monkeypatch):
    monkeypatch.setenv("GREYLINE_MOMENTUM_EQUITY_SHADOW", "false")
    assert M().mark()["status"] == "MOM_SHADOW_DISABLED"


def test_open_cohort_then_no_double_open_while_immature(monkeypatch):
    # entry at idx 0; not enough bars to mature (need > idx+5) -> cohort opens and STAYS open
    _stub_signal(monkeypatch, [{"symbol": "AAA", "side": "BUY", "last_close": 100.0, "_entry_idx": 0}])
    _stub_bars(monkeypatch, {"AAA": [100.0, 101.0, 102.0]})     # len 3, idx0+5=5 not reached
    r1 = M().mark()
    assert r1["cohort_opened"] is True and r1["open_cohorts"] == 1
    # a second mark with a fresh signal must NOT open a 2nd overlapping cohort (non-overlapping weekly)
    _stub_signal(monkeypatch, [{"symbol": "BBB", "side": "BUY", "last_close": 50.0, "_entry_idx": 0}])
    r2 = M().mark()
    assert r2["cohort_opened"] is False and r2["open_cohorts"] == 1


def test_settles_a_long_with_correct_net_return(monkeypatch):
    _stub_signal(monkeypatch, [{"symbol": "AAA", "side": "BUY", "last_close": 100.0, "_entry_idx": 0}])
    _stub_bars(monkeypatch, {"AAA": [100.0, 0, 0, 0, 0, 104.0]})   # idx5 = exit = 104 -> +4% gross
    M().mark()                                                     # open
    r = M().mark()                                                 # idx0+5=5, len 6 > 5 -> settle, then ROLL
    # on settle the basket rolls straight into a fresh cohort (maturity == the weekly rebalance point)
    assert r["cohorts_closed"] == 1 and r["open_cohorts"] == 1
    closed = [json.loads(l) for l in M.CLOSED.read_text().splitlines() if l.strip()]
    assert len(closed) == 1
    # gross +0.04, minus 10bps round-trip = 0.0390
    assert closed[0]["gross_return"] == pytest.approx(0.04, abs=1e-6)
    assert closed[0]["net_return"] == pytest.approx(0.039, abs=1e-6)


def test_short_leg_return_is_inverted(monkeypatch):
    _stub_signal(monkeypatch, [{"symbol": "SSS", "side": "SELL", "last_close": 100.0, "_entry_idx": 0}])
    _stub_bars(monkeypatch, {"SSS": [100.0, 0, 0, 0, 0, 102.0]})   # price ROSE 2% -> short LOSES 2%
    M().mark()
    M().mark()
    closed = [json.loads(l) for l in M.CLOSED.read_text().splitlines() if l.strip()]
    assert closed[0]["gross_return"] == pytest.approx(100.0 / 102.0 - 1, abs=1e-6)   # ≈ -0.0196


def test_cohort_return_is_leg_mean(monkeypatch):
    _stub_signal(monkeypatch, [
        {"symbol": "AAA", "side": "BUY", "last_close": 100.0, "_entry_idx": 0},
        {"symbol": "BBB", "side": "BUY", "last_close": 100.0, "_entry_idx": 0},
    ])
    _stub_bars(monkeypatch, {"AAA": [100.0, 0, 0, 0, 0, 110.0],    # +10%
                             "BBB": [100.0, 0, 0, 0, 0, 100.0]})   # 0%
    M().mark()
    M().mark()
    closed = [json.loads(l) for l in M.CLOSED.read_text().splitlines() if l.strip()]
    assert closed[0]["gross_return"] == pytest.approx(0.05, abs=1e-6)          # mean(0.10, 0)
    assert closed[0]["net_return"] == pytest.approx(0.049, abs=1e-6)           # minus 10bps


def test_open_positions_shows_unrealized_and_days_to_settle(monkeypatch):
    _stub_signal(monkeypatch, [{"symbol": "AAA", "side": "BUY", "last_close": 100.0, "_entry_idx": 0,
                                "conviction": 1.9}])
    _stub_bars(monkeypatch, {"AAA": [100.0, 103.0]})    # 1 bar elapsed, price +3%, not yet matured
    M().mark()
    pos = M().open_positions()
    assert len(pos) == 1
    p = pos[0]
    assert p["symbol"] == "AAA" and p["side"] == "BUY"
    assert p["unrealized_pct"] == pytest.approx(3.0, abs=1e-6)
    assert p["days_held"] == 1 and p["days_to_settle"] == M.HOLD_DAYS - 1
    assert set(M().open_symbols()) == {"AAA"}


def test_bench_cache_written_for_the_board(monkeypatch):
    _stub_signal(monkeypatch, [{"symbol": "AAA", "side": "BUY", "last_close": 100.0, "_entry_idx": 0,
                                "conviction": 1.9, "momentum_12_1_pct": 40.0, "reversal_5d_move_pct": -3.0,
                                "directional_bias": "BULLISH", "momentum_rank": 0.9, "reversal_rank": 0.8}])
    _stub_bars(monkeypatch, {"AAA": [100.0, 101.0]})
    M().mark()
    cache = json.loads(M.BENCH_CACHE.read_text())
    # data_source must be a reality-guard-whitelisted REAL source (settled CSV bars), not a made-up label
    # that trips DATA_SOURCE_REAL; provenance is carried separately.
    assert cache["status"] == "TOP_CANDIDATES_READY" and cache["data_source"] == "CSV_HISTORICAL"
    assert cache["refreshed_by"] == "MomentumReversalShadowEngine"
    assert cache["candidates"][0]["symbol"] == "AAA" and cache["candidates"][0]["rank"] == 1
    assert "computed_epoch" in cache          # freshness stamp the board/route read


def test_report_gating_accumulating_then_measuring(monkeypatch):
    _stub_signal(monkeypatch, [{"symbol": "AAA", "side": "BUY", "last_close": 100.0, "_entry_idx": 0}])
    r0 = M().report()
    assert r0["status"] == "MOM_SHADOW_NO_DATA"
    # seed MIN_COHORTS-1 closed cohorts -> ACCUMULATING; then one more -> MEASURING
    lines = [json.dumps({"net_return": 0.001, "n_legs": 1}) for _ in range(M.MIN_COHORTS - 1)]
    M.CLOSED.write_text("\n".join(lines) + "\n")
    assert M().report()["status"] == "MOM_SHADOW_ACCUMULATING"
    with open(M.CLOSED, "a") as f:
        f.write(json.dumps({"net_return": 0.001, "n_legs": 1}) + "\n")
    rep = M().report()
    assert rep["status"] == "MOM_SHADOW_MEASURING"
    assert rep["cohorts_closed"] == M.MIN_COHORTS and "annualized_sharpe" in rep
