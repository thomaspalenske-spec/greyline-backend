"""Momentum-reversal EQUITY shadow (LIVE / time-based): opens only on a real live feed, refuses stale CSV
fallback, settles after HOLD_DAYS business days at live quotes, per-cohort net-return math, report gating.
Fully isolated state + stubbed signal/quotes/clock — no network, no broker, no real ledger touched."""

import json
import time

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


def _stub_signal(monkeypatch, picks, source="TRADESTATION_LIVE", asof="2026-08-10"):
    # (top_n targets, full clean bench, as_of, top_n, source)
    monkeypatch.setattr(M, "_signal_targets",
                        lambda self, prefer_live=True: ([dict(p) for p in picks], [dict(p) for p in picks], asof, len(picks), source))


def _stub_prices(monkeypatch, prices):
    monkeypatch.setattr(M, "_live_prices", lambda self, syms, _p=prices: {s: _p[s] for s in
                        {str(x).upper() for x in syms} if s in _p})


def test_disabled(monkeypatch):
    monkeypatch.setenv("GREYLINE_MOMENTUM_EQUITY_SHADOW", "false")
    assert M().mark()["status"] == "MOM_SHADOW_DISABLED"


def test_opens_on_live_feed_then_no_double_open(monkeypatch):
    _stub_signal(monkeypatch, [{"symbol": "AAA", "side": "BUY", "last_close": 100.0}], source="TRADESTATION_LIVE")
    _stub_prices(monkeypatch, {})
    monkeypatch.setattr(M, "_biz_days_elapsed", lambda self, d: 0)     # freshly opened
    r1 = M().mark()
    assert r1["cohort_opened"] is True and r1["open_cohorts"] == 1
    # second mark, still within the hold -> must NOT open a 2nd overlapping cohort
    _stub_signal(monkeypatch, [{"symbol": "BBB", "side": "BUY", "last_close": 50.0}], source="TRADESTATION_LIVE")
    r2 = M().mark()
    assert r2["cohort_opened"] is False and r2["open_cohorts"] == 1


def test_refuses_to_open_on_stale_csv_fallback(monkeypatch):
    # the core fix: if the universe fetch fell back to CSV, DON'T open on stale prices
    _stub_signal(monkeypatch, [{"symbol": "AAA", "side": "BUY", "last_close": 100.0}], source="CSV_HISTORICAL")
    _stub_prices(monkeypatch, {})
    r = M().mark()
    assert r["cohort_opened"] is False and r["open_cohorts"] == 0
    assert "stale" in r.get("open_skipped", "").lower()


def test_settles_after_hold_at_live_quotes(monkeypatch):
    M.OPEN.write_text(json.dumps([{
        "opened": "2026-08-01", "source": "TRADESTATION_LIVE",
        "legs": [{"symbol": "AAA", "side": "BUY", "entry_close": 100.0},
                 {"symbol": "SSS", "side": "SELL", "entry_close": 100.0}]}]))
    monkeypatch.setattr(M, "_biz_days_elapsed", lambda self, d: 5)          # hold complete
    _stub_prices(monkeypatch, {"AAA": 110.0, "SSS": 90.0})                  # long +10%, short: 100/90-1 = +11.1%
    _stub_signal(monkeypatch, [], source="TRADESTATION_LIVE")              # nothing to re-open with
    r = M().mark()
    assert r["cohorts_closed"] == 1 and r["open_cohorts"] == 0
    rec = json.loads(M.CLOSED.read_text().splitlines()[-1])
    exp_gross = ((110/100 - 1) + (100/90 - 1)) / 2
    assert rec["gross_return"] == pytest.approx(exp_gross, abs=1e-6)
    assert rec["net_return"] == pytest.approx(exp_gross - 0.001, abs=1e-6)   # minus 10bps


def test_does_not_settle_before_hold(monkeypatch):
    M.OPEN.write_text(json.dumps([{
        "opened": "2026-08-10", "source": "TRADESTATION_LIVE",
        "legs": [{"symbol": "AAA", "side": "BUY", "entry_close": 100.0}]}]))
    monkeypatch.setattr(M, "_biz_days_elapsed", lambda self, d: 3)          # not yet 5 business days
    _stub_prices(monkeypatch, {"AAA": 120.0})
    _stub_signal(monkeypatch, [], source="TRADESTATION_LIVE")
    r = M().mark()
    assert r["cohorts_closed"] == 0 and r["open_cohorts"] == 1


def test_open_positions_live_direction_and_days(monkeypatch):
    M.OPEN.write_text(json.dumps([{
        "opened": "2026-08-05", "source": "TRADESTATION_LIVE",
        "legs": [{"symbol": "AAA", "side": "BUY", "entry_close": 100.0, "conviction": 1.9}]}]))
    monkeypatch.setattr(M, "_biz_days_elapsed", lambda self, d: 2)
    _stub_prices(monkeypatch, {"AAA": 103.0})
    pos = M().open_positions()
    p = pos[0]
    assert p["live_last"] == 103.0 and p["live_pct"] == pytest.approx(3.0) and p["live_dir"] == "up"
    assert p["days_held"] == 2 and p["days_to_settle"] == M.HOLD_DAYS - 2


def test_biz_days_elapsed_counts_weekdays_only():
    # Fri 2026-08-07 -> Mon 2026-08-10 is ONE business day (skips the weekend)
    class _M(M):
        @staticmethod
        def _today():
            import datetime
            return datetime.date(2026, 8, 10)
    assert _M()._biz_days_elapsed("2026-08-07") == 1
    assert _M()._biz_days_elapsed("2026-08-03") == 5      # Mon->Mon = 5 business days


def test_signal_targets_reads_scan_cache_fresh_vs_stale():
    # FRESH + live-sourced scan -> usable source; the shadow opens on it
    M.BENCH_CACHE.write_text(json.dumps({
        "data_source": "TRADESTATION_LIVE", "as_of": "2026-08-10", "computed_epoch": time.time(),
        "candidates": [{"symbol": "AAA", "side": "BUY", "last_close": 100.0, "conviction": 1.9}]}))
    picks, bench, asof, top_n, source = M()._signal_targets()
    assert source == "TRADESTATION_LIVE" and picks and picks[0]["symbol"] == "AAA"
    # STALE scan (old epoch) -> STALE_SCAN, mark() must refuse to open on it
    M.BENCH_CACHE.write_text(json.dumps({
        "data_source": "TRADESTATION_LIVE", "as_of": "2026-07-01", "computed_epoch": time.time() - 5 * 86400,
        "candidates": [{"symbol": "AAA", "side": "BUY", "last_close": 100.0}]}))
    _picks, _b, _a, _n, source2 = M()._signal_targets()
    assert source2 == "STALE_SCAN"


def test_report_gating_accumulating_then_measuring(monkeypatch):
    _stub_prices(monkeypatch, {})
    # no open cohort + no live scan cache -> honestly reports it is WAITING for a fresh scan
    assert M().report()["status"] == "MOM_SHADOW_WAITING_SCAN"
    lines = [json.dumps({"net_return": 0.001, "n_legs": 1}) for _ in range(M.MIN_COHORTS - 1)]
    M.CLOSED.write_text("\n".join(lines) + "\n")
    assert M().report()["status"] == "MOM_SHADOW_ACCUMULATING"
    with open(M.CLOSED, "a") as f:
        f.write(json.dumps({"net_return": 0.001, "n_legs": 1}) + "\n")
    rep = M().report()
    assert rep["status"] == "MOM_SHADOW_MEASURING" and rep["cohorts_closed"] == M.MIN_COHORTS
