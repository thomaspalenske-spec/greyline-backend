"""Entries wait for the liquid mid-session; the open/close spread tax is not paid on a multi-day
thesis. Exits are never gated here."""

from datetime import datetime

from app.services.session_liquidity_window_engine import SessionLiquidityWindowEngine
from app.services.market_hours_engine import MarketHoursEngine


def _et(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=MarketHoursEngine.MARKET_TZ)


def test_first_minutes_after_open_are_not_liquid(monkeypatch):
    monkeypatch.setattr(MarketHoursEngine, "status",
                        lambda self: {"is_regular_session": True, "market_time": "x"})
    e = SessionLiquidityWindowEngine()
    s = e.status(now_et=_et(2026, 7, 27, 9, 35))     # a Monday, 5 min after open
    assert s["in_liquid_window"] is False
    assert "OPENING" in s["reason"]


def test_last_minutes_before_close_are_not_liquid(monkeypatch):
    monkeypatch.setattr(MarketHoursEngine, "status",
                        lambda self: {"is_regular_session": True, "market_time": "x"})
    e = SessionLiquidityWindowEngine()
    s = e.status(now_et=_et(2026, 7, 27, 15, 50))    # 10 min before close
    assert s["in_liquid_window"] is False
    assert "CLOSING" in s["reason"]


def test_midday_is_liquid(monkeypatch):
    monkeypatch.setattr(MarketHoursEngine, "status",
                        lambda self: {"is_regular_session": True, "market_time": "x"})
    e = SessionLiquidityWindowEngine()
    s = e.status(now_et=_et(2026, 7, 27, 11, 30))
    assert s["in_liquid_window"] is True and s["reason"] == "LIQUID_WINDOW"


def test_closed_market_is_never_liquid(monkeypatch):
    monkeypatch.setattr(MarketHoursEngine, "status",
                        lambda self: {"is_regular_session": False, "market_time": "x"})
    e = SessionLiquidityWindowEngine()
    s = e.status(now_et=_et(2026, 7, 27, 11, 30))
    assert s["in_liquid_window"] is False


def test_skip_windows_are_env_tunable(monkeypatch):
    monkeypatch.setattr(MarketHoursEngine, "status",
                        lambda self: {"is_regular_session": True, "market_time": "x"})
    monkeypatch.setenv("GREYLINE_LIQUIDITY_OPEN_SKIP_MIN", "45")
    e = SessionLiquidityWindowEngine()
    s = e.status(now_et=_et(2026, 7, 27, 10, 0))     # 30 min after open, but skip is 45
    assert s["in_liquid_window"] is False
