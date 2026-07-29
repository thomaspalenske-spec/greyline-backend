"""Hermetic tests for EarningsVolHarvestEngine — no live chain, no orders.

Covers: gating, candidate filtering (rich IV + reporting soon + dedup), and dry-run respecting the
daily limit / risk cap. The engine reuses the VRP condor builder + ledger, so defined-risk sizing and
reconciliation are covered by the VRP tests; here we verify the earnings-specific selection.
"""

import json
from datetime import date, datetime, timezone

import app.services.conditional_vrp_short_premium_engine as vrp_mod
import app.services.tradestation_option_chain_live_engine as chain_mod
from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine as ENG

TODAY = datetime.now(timezone.utc).date()


def _iso(days):
    return date.fromordinal(TODAY.toordinal() + days).isoformat()


def _panel(tmp_path, records):
    p = tmp_path / "panel.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records))
    return p


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_EARNINGS_VOL_ENABLED", "false")
    r = ENG().open_positions(dry_run=False)
    assert r["status"] == "EARNINGS_VOL_DISABLED" and r["opened"] == 0


def test_candidates_filter_rich_iv_and_soon(monkeypatch, tmp_path):
    recs = [
        {"kind": "implied", "ticker": "AAA", "report_date": _iso(1), "iv_rank": 0.70, "implied_move_pct": 8},
        {"kind": "implied", "ticker": "FAR", "report_date": _iso(10), "iv_rank": 0.90, "implied_move_pct": 9},  # too far
        {"kind": "implied", "ticker": "LOW", "report_date": _iso(1), "iv_rank": 0.30, "implied_move_pct": 7},   # IV too low
        {"kind": "implied", "ticker": "BBB", "report_date": _iso(2), "iv_rank": 0.85, "implied_move_pct": 10},
        {"kind": "implied", "ticker": "HII", "report_date": _iso(1), "iv_rank": 80.0, "implied_move_pct": 9},   # 0-100 scale, rich
        {"kind": "implied", "ticker": "LOO", "report_date": _iso(1), "iv_rank": 40.0, "implied_move_pct": 6},   # 0-100 scale, NOT rich
        {"kind": "implied", "ticker": "TDY", "report_date": _iso(0), "iv_rank": 0.90, "implied_move_pct": 9},   # reports TODAY -> excluded
    ]
    eng = ENG()
    monkeypatch.setattr(ENG, "PANEL", _panel(tmp_path, recs))
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    cands = eng._candidates(today=TODAY)
    tickers = [c["ticker"] for c in cands]
    assert "AAA" in tickers and "BBB" in tickers and "HII" in tickers      # rich (0-1 and 0-100 scales)
    assert "FAR" not in tickers and "LOW" not in tickers and "LOO" not in tickers and "TDY" not in tickers
    # normalized iv_rank stored as 0-1 (HII 80 -> 0.80) so downstream richness buckets match
    assert next(c for c in cands if c["ticker"] == "HII")["iv_rank"] == 0.8


def test_candidates_dedup_against_open(monkeypatch, tmp_path):
    recs = [{"kind": "implied", "ticker": "AAA", "report_date": _iso(1), "iv_rank": 0.7, "implied_move_pct": 8}]
    eng = ENG()
    monkeypatch.setattr(ENG, "PANEL", _panel(tmp_path, recs))
    monkeypatch.setattr(eng, "_open_symbols", lambda: {"AAA"})   # already positioned
    assert eng._candidates(today=TODAY) == []


def test_dryrun_respects_daily_limit(monkeypatch):
    monkeypatch.setenv("GREYLINE_EARNINGS_VOL_ENABLED", "true")
    eng = ENG()
    monkeypatch.setattr(eng, "_candidates", lambda today=None: [
        {"ticker": t, "report_date": _iso(1), "days_to_report": 1, "iv_rank": 0.8, "implied_move_pct": 8}
        for t in ("AAA", "BBB", "CCC", "DDD")])
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    monkeypatch.setattr(eng, "_open_risk", lambda: 0.0)
    monkeypatch.setattr(eng, "_expiry_after", lambda s, rd: _iso(9))

    class FakeChain:
        def get_chain_snapshot(self, **k):
            return {"contracts": [{"x": 1}]}
    monkeypatch.setattr(chain_mod, "TradeStationOptionChainLiveEngine", FakeChain)
    condor = {"symbol": "X", "quantity": 1, "credit_total": 40.0, "max_loss_total": 200.0,
              "credit_per_condor": 0.4, "return_on_risk": 0.2,
              "legs": {"short_call": {}, "wing_call": {}, "short_put": {}, "wing_put": {}}}
    monkeypatch.setattr(vrp_mod.ConditionalVRPShortPremiumEngine, "build_condor",
                        lambda self, sym, contracts, **k: dict(condor, symbol=sym))

    r = eng.open_positions(dry_run=True)
    assert r["status"] == "EARNINGS_VOL_DRYRUN"
    assert r["planned"] == eng.LIMIT_PER_DAY          # capped at 2/day, not all 4


def test_dryrun_respects_risk_cap(monkeypatch):
    monkeypatch.setenv("GREYLINE_EARNINGS_VOL_ENABLED", "true")
    eng = ENG()
    monkeypatch.setattr(eng, "_candidates", lambda today=None: [
        {"ticker": t, "report_date": _iso(1), "days_to_report": 1, "iv_rank": 0.8, "implied_move_pct": 8}
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE")])
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    monkeypatch.setattr(eng, "_open_risk", lambda: 800.0)         # only $100 headroom under $900 cap
    monkeypatch.setattr(eng, "_expiry_after", lambda s, rd: _iso(9))

    class FakeChain:
        def get_chain_snapshot(self, **k):
            return {"contracts": [{"x": 1}]}
    monkeypatch.setattr(chain_mod, "TradeStationOptionChainLiveEngine", FakeChain)
    monkeypatch.setattr(vrp_mod.ConditionalVRPShortPremiumEngine, "build_condor",
                        lambda self, sym, contracts, **k: {"symbol": sym, "quantity": 1,
                        "credit_total": 40.0, "max_loss_total": 200.0, "credit_per_condor": 0.4,
                        "return_on_risk": 0.2, "legs": {}})
    r = eng.open_positions(dry_run=True)
    assert r["planned"] == 0                           # a $200 condor doesn't fit $100 headroom
