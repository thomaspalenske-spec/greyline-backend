"""Daily sector-map refresh: shares the optionable engine's screener fetch, merges, never clobbers.

No network — the HTTP layer and the fetch are monkeypatched.
"""

import json

import app.services.sector_map_engine as sme
from app.services.sector_map_engine import SectorMapEngine
import app.services.optionable_universe_engine as oue
from app.services.optionable_universe_engine import OptionableUniverseEngine


def test_optionable_fetch_is_cached_so_the_sector_map_costs_no_extra_call(monkeypatch):
    calls = {"n": 0}

    class Resp:
        status_code = 200

        def json(self):
            return {"data": [{"ticker": "NVDA", "sector": "Technology"}]}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return Resp()

    monkeypatch.setattr(oue.requests, "get", fake_get)
    OptionableUniverseEngine._fetch_cache = {}
    o = OptionableUniverseEngine()
    o._fetch("total_open_interest")
    o._fetch("total_open_interest")     # second consumer (the sector map) in the same window
    assert calls["n"] == 1              # one UW hit feeds both


def test_regenerate_merges_and_never_drops(monkeypatch, tmp_path):
    monkeypatch.setattr(sme, "OUT", tmp_path / "sm.json")
    (tmp_path / "sm.json").write_text(json.dumps({"sectors": {"OLDNAME": "ENERGY"}}))
    fresh = {"NVDA": "TECHNOLOGY", **{f"F{i}": "TECHNOLOGY" for i in range(320)}}   # >= MIN_ACCEPTABLE
    monkeypatch.setattr(SectorMapEngine, "_fetch_sectors", lambda self: fresh)
    monkeypatch.setattr(SectorMapEngine, "_traded_universe", lambda self: set())
    SectorMapEngine().regenerate(session_date="2026-07-31")
    saved = json.loads((tmp_path / "sm.json").read_text())["sectors"]
    assert saved["OLDNAME"] == "ENERGY" and saved["NVDA"] == "TECHNOLOGY"   # prior kept + new added


def test_thin_fetch_does_not_clobber_the_map(monkeypatch, tmp_path):
    monkeypatch.setattr(sme, "OUT", tmp_path / "sm.json")
    (tmp_path / "sm.json").write_text(json.dumps({"sectors": {"OLDNAME": "ENERGY"}}))
    monkeypatch.setattr(SectorMapEngine, "_fetch_sectors", lambda self: {"A": "X"})   # < MIN_ACCEPTABLE
    r = SectorMapEngine().regenerate()
    assert r["persisted"] is False
    assert json.loads((tmp_path / "sm.json").read_text())["sectors"] == {"OLDNAME": "ENERGY"}


def _mh(iso, weekday=True, holiday=False):
    return {"market_time": iso, "is_weekday": weekday, "is_holiday": holiday}


def test_refreshes_once_per_trading_day_post_close(monkeypatch, tmp_path):
    monkeypatch.setattr(sme, "OUT", tmp_path / "sm.json")
    big = {f"S{i}": "X" for i in range(400)}
    monkeypatch.setattr(SectorMapEngine, "regenerate",
                        lambda self, session_date=None: {"status": "SECTOR_MAP_READY", "symbols": 400})

    (tmp_path / "sm.json").write_text(json.dumps({"sectors": big, "session_date": "2026-07-30"}))
    assert SectorMapEngine().recompute_if_due(_mh("2026-07-31T16:05:00-04:00"))["ran"] is True   # new day
    (tmp_path / "sm.json").write_text(json.dumps({"sectors": big, "session_date": "2026-07-31"}))
    assert SectorMapEngine().recompute_if_due(_mh("2026-07-31T16:30:00-04:00"))["ran"] is False  # done today
    assert SectorMapEngine().recompute_if_due(_mh("2026-07-31T10:00:00-04:00"))["ran"] is False  # pre-close
