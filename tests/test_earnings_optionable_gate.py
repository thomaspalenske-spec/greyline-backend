"""The earnings-condor feed of the Iron Condor table draws from the SAME optionable universe as VRP,
so both feeds share one universe and earnings condors only form on deeply-tradeable names.

Fail-safe: if the universe can't be resolved, the feed is left ungated (never emptied). No network.
"""

import json
from datetime import date, timedelta

from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine


def _panel(tmp_path, rows):
    p = tmp_path / "panel.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def test_earnings_candidates_gated_by_optionable_universe(monkeypatch, tmp_path):
    eng = EarningsVolHarvestEngine()
    rd = (date.today() + timedelta(days=1)).isoformat()          # reports tomorrow (within 1-2 days)
    eng.PANEL = _panel(tmp_path, [
        {"kind": "implied", "ticker": "AMZN", "report_date": rd, "iv_rank": 90, "implied_move_pct": 5.0},
        {"kind": "implied", "ticker": "TINYCO", "report_date": rd, "iv_rank": 95, "implied_move_pct": 8.0},
    ])
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    monkeypatch.setattr(eng, "_optionable_universe", lambda: {"AMZN"})   # only AMZN is optionable
    cands = [c["ticker"] for c in eng._candidates(today=date.today())]
    assert cands == ["AMZN"]                                     # TINYCO gated out despite higher IV rank


def test_earnings_feed_ungated_when_universe_unavailable(monkeypatch, tmp_path):
    eng = EarningsVolHarvestEngine()
    rd = (date.today() + timedelta(days=1)).isoformat()
    eng.PANEL = _panel(tmp_path, [
        {"kind": "implied", "ticker": "TINYCO", "report_date": rd, "iv_rank": 95, "implied_move_pct": 8.0}])
    monkeypatch.setattr(eng, "_open_symbols", lambda: set())
    monkeypatch.setattr(eng, "_optionable_universe", lambda: None)       # hard failure → fail-safe
    cands = [c["ticker"] for c in eng._candidates(today=date.today())]
    assert cands == ["TINYCO"]                                   # never silently emptied
