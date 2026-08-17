"""Daily-loss HALT now AUTO-blocks new opens at the choke point (was alert-only). On a -7% breach the
MissionRiskGovernor writes opens_halted; place_order/place_multileg then refuse OPENING orders while it's
set, while exits/covers/stops still pass so the book can de-risk. Mirrors the master kill switch. No real
orders: the blocked path returns before any network call."""

import app.services.tradestation_sim_booking_engine as mod
from app.services.tradestation_sim_booking_engine import (
    TradeStationSimBookingEngine, _is_opening_order, _daily_loss_halted)

# Capture the REAL methods before conftest's autouse fixture swaps them for stubs.
_REAL_PLACE_ORDER = TradeStationSimBookingEngine.__dict__["place_order"]
_REAL_PLACE_MULTI = TradeStationSimBookingEngine.__dict__["place_multileg"]


def _setup(monkeypatch, halted):
    monkeypatch.setattr(mod, "reload_env", lambda *a, **k: None)
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")     # master ON -> isolate the loss gate
    monkeypatch.setenv("GREYLINE_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setattr(mod, "_daily_loss_halted", lambda: halted)


def test_halted_blocks_an_opening_buy(monkeypatch):
    _setup(monkeypatch, halted=True)
    r = _REAL_PLACE_ORDER(TradeStationSimBookingEngine(), "USMV", 3,
                          action="BUY", order_type="Limit", limit_price=100.0)
    assert r["ok"] is False and r.get("daily_loss_halted") is True and r.get("execution_blocked") is True
    assert "daily-loss HALT" in r["reject_reason"]


def test_halted_blocks_an_opening_spread(monkeypatch):
    _setup(monkeypatch, halted=True)
    legs = [{"symbol": "X 1", "action": "SELLTOOPEN"}, {"symbol": "X 2", "action": "BUYTOOPEN"}]
    r = _REAL_PLACE_MULTI(TradeStationSimBookingEngine(), legs)
    assert r["ok"] is False and r.get("daily_loss_halted") is True


def test_exits_and_stops_bypass_the_halt_gate():
    # the gate is `_is_opening_order AND halted`; a close/cover/stop is never an opening order -> never gated
    for a in ("SELL", "SELLTOCLOSE", "BUYTOCLOSE", "BUYTOCOVER"):
        assert not _is_opening_order(a), a
    assert not _is_opening_order("BUY", order_type="StopMarket")       # protective stop passes even halted


def test_daily_loss_halted_reads_the_governor_marker(monkeypatch):
    import app.services.mission_risk_governor_engine as gmod
    monkeypatch.setattr(gmod.MissionRiskGovernorEngine, "opens_halted", lambda self: True)
    assert _daily_loss_halted() is True
    monkeypatch.setattr(gmod.MissionRiskGovernorEngine, "opens_halted", lambda self: False)
    assert _daily_loss_halted() is False


def test_daily_loss_halted_fails_open_on_error(monkeypatch):
    import app.services.mission_risk_governor_engine as gmod

    def _boom(self):
        raise RuntimeError("boom")
    monkeypatch.setattr(gmod.MissionRiskGovernorEngine, "opens_halted", _boom)
    assert _daily_loss_halted() is False       # fail-open: a transient glitch must not freeze trading
