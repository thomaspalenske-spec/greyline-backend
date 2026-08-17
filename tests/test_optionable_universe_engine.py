"""The VRP/condor universe is DERIVED from live option liquidity, not hand-typed — and fails safe.

These tests never hit the network (the live screener fetch is monkeypatched) and never place orders.
"""

import json

import pytest

from app.services.optionable_universe_engine import OptionableUniverseEngine
import app.services.optionable_universe_engine as oue
from app.services.vrp_research_engine import VRPResearchEngine


def _row(ticker, oi, cap, itype="Common Stock", iv=0.3, is_index=False):
    return {"ticker": ticker, "total_open_interest": oi, "marketcap": cap, "issue_type": itype,
            "iv30d": iv, "iv_rank": 55.0, "is_index": is_index, "sector": "Technology",
            "avg_30_day_call_volume": 1000, "avg_30_day_put_volume": 800,
            "variance_risk_premium": 0.01}


@pytest.fixture
def eng(monkeypatch, tmp_path):
    monkeypatch.setattr(oue, "CACHE", tmp_path / "optionable_universe.json")
    return OptionableUniverseEngine()


def test_screen_applies_all_rules(eng, monkeypatch):
    raw = [
        _row("NVDA", 5_000_000, 4_000e9),                       # keep — deep OI, mega cap
        _row("SPY", 18_000_000, 700e9, itype="ETF"),            # keep — ETF, deep OI (cap exempt)
        _row("SPX", 16_000_000, 0, itype="", is_index=True),    # drop — cash-settled index
        _row("AMC", 3_000_000, 2e9),                            # drop — below $10B cap floor (meme)
        _row("THIN", 100_000, 50e9),                            # drop — option OI below 250k floor
        _row("NOIV", 4_000_000, 50e9, iv=0),                    # drop — no live IV surface
        _row("BABA", 4_000_000, 200e9, itype="ADR"),            # drop — ADR not in allowed types
        _row("SPXW", 5_000_000, 0, itype="", is_index=True),    # drop — non-alnum + index
    ]
    monkeypatch.setattr(eng, "_fetch", lambda order="total_open_interest": raw)
    kept = eng.screen()
    tickers = [r["ticker"] for r in kept]
    assert tickers == ["SPY", "NVDA"]                           # ranked by OI desc, junk removed
    assert all(r["total_open_interest"] >= eng.min_oi for r in kept)


def test_target_size_caps_membership(eng, monkeypatch):
    raw = [_row(f"T{i:03d}", 5_000_000 - i, 50e9) for i in range(300)]
    monkeypatch.setattr(eng, "_fetch", lambda order="total_open_interest": raw)
    monkeypatch.setenv("GREYLINE_OPTIONABLE_TARGET_SIZE", "120")
    assert len(eng.screen()) == 120


def test_recompute_persists_and_names_reads_back(eng, monkeypatch):
    raw = [_row(f"BIG{i:03d}", 5_000_000 - i, 50e9) for i in range(60)]
    monkeypatch.setattr(eng, "_fetch", lambda order="total_open_interest": raw)
    out = eng.recompute()
    assert out["persisted"] is True and out["count"] == 60
    assert eng.names()[0] == "BIG000"                           # richest-OI first, read from cache


def test_thin_screen_fails_safe_without_persisting(eng, monkeypatch):
    # Fewer than MIN_ACCEPTABLE survivors = a broken screen: must NOT persist, must NOT empty anything.
    monkeypatch.setattr(eng, "_fetch", lambda order="total_open_interest": [_row("NVDA", 5_000_000, 4_000e9)])
    out = eng.recompute()
    assert out["persisted"] is False and out["status"] == "OPTIONABLE_UNIVERSE_SCREEN_FAILED"
    assert eng.names() is None                                  # nothing cached → caller falls back


def test_names_none_when_cache_missing(eng):
    assert eng.names() is None


def test_vrp_default_names_uses_derived_when_available(monkeypatch):
    monkeypatch.setattr(OptionableUniverseEngine, "names", lambda self: ["AAA", "BBB", "CCC"])
    assert VRPResearchEngine().DEFAULT_NAMES == ["AAA", "BBB", "CCC"]


def test_vrp_default_names_falls_back_to_curated(monkeypatch):
    monkeypatch.setattr(OptionableUniverseEngine, "names", lambda self: None)
    dn = VRPResearchEngine().DEFAULT_NAMES
    assert dn is VRPResearchEngine.CURATED_FALLBACK
    assert "SPY" in dn and len(dn) > 100                        # the real curated safety net


def test_vrp_default_names_survives_engine_exception(monkeypatch):
    def boom(self):
        raise RuntimeError("UW down")
    monkeypatch.setattr(OptionableUniverseEngine, "names", boom)
    assert VRPResearchEngine().DEFAULT_NAMES is VRPResearchEngine.CURATED_FALLBACK


# ---- daily-at-close refresh gate ------------------------------------------------------------------

def _mh(et_iso, weekday=True, holiday=False):
    return {"market_time": et_iso, "is_weekday": weekday, "is_holiday": holiday}


def _seed_cache(session_date="2020-01-01"):
    oue.CACHE.parent.mkdir(parents=True, exist_ok=True)
    oue.CACHE.write_text(json.dumps({"tickers": [f"T{i}" for i in range(60)], "count": 60,
                                     "session_date": session_date}))


def _stub_screen(eng, monkeypatch):
    monkeypatch.setattr(eng, "_fetch",
                        lambda order="total_open_interest": [_row(f"BIG{i:03d}", 5_000_000 - i, 50e9)
                                                             for i in range(60)])


def test_bootstrap_screens_when_no_cache_regardless_of_time(eng, monkeypatch):
    _stub_screen(eng, monkeypatch)
    out = eng.recompute_if_due(_mh("2026-07-30T10:00:00-04:00"))   # intraday, but no cache yet
    assert out["ran"] is True and out["trigger"] == "bootstrap"


def test_refreshes_once_at_post_close_on_a_new_day(eng, monkeypatch):
    _seed_cache(session_date="2026-07-29")
    _stub_screen(eng, monkeypatch)
    out = eng.recompute_if_due(_mh("2026-07-30T16:05:00-04:00"))   # after 16:00 ET, new session
    assert out["ran"] is True and out["trigger"] == "post_close_refresh"
    assert json.loads(oue.CACHE.read_text())["session_date"] == "2026-07-30"


def test_does_not_refresh_twice_same_day(eng, monkeypatch):
    _seed_cache(session_date="2026-07-30")
    _stub_screen(eng, monkeypatch)
    out = eng.recompute_if_due(_mh("2026-07-30T16:30:00-04:00"))   # already refreshed today
    assert out["ran"] is False and out["status"] == "OPTIONABLE_UNIVERSE_FRESH"


def test_does_not_refresh_intraday_before_close(eng, monkeypatch):
    _seed_cache(session_date="2026-07-29")
    _stub_screen(eng, monkeypatch)
    out = eng.recompute_if_due(_mh("2026-07-30T10:00:00-04:00"))   # before the close
    assert out["ran"] is False


def test_does_not_refresh_on_weekend_or_holiday(eng, monkeypatch):
    _seed_cache(session_date="2026-07-29")
    _stub_screen(eng, monkeypatch)
    assert eng.recompute_if_due(_mh("2026-08-01T17:00:00-04:00", weekday=False))["ran"] is False
    assert eng.recompute_if_due(_mh("2026-07-30T17:00:00-04:00", holiday=True))["ran"] is False
