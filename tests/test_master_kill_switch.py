"""Master execution kill switch — one switch that halts autonomous OPENING for every sleeve.

Before this, only momentum + ExecutionGovernor honored GREYLINE_PAPER_EXECUTION_ENABLED; trend/low_vol/
xs/carry booked straight through place_order and ignored it, so flipping the "master" off did NOT stop
them (2026-08-08 gap). The switch is now enforced at the single choke point (place_order / place_multileg)
so it cannot be bypassed — and it blocks ONLY opens, never exits, so the book can always be flattened.

No real broker orders: the blocked path returns before any network call; the allowed path is asserted via
the pure classifier, never by placing an order (conftest also hard-blocks place_order).
"""

from app.services.tradestation_sim_booking_engine import (
    TradeStationSimBookingEngine, _is_opening_order, _master_execution_on, _OPENING_ACTIONS)

# Capture the REAL place_order at import time, before conftest's autouse fixture swaps it for a stub.
_REAL_PLACE_ORDER = TradeStationSimBookingEngine.__dict__["place_order"]


def _set_master(monkeypatch, on):
    # The engine's __init__ calls reload_env(), which would revert these to the on-disk .env values.
    # Neutralize it so the test's env is authoritative (production reads the durable .env, which is correct).
    import app.services.tradestation_sim_booking_engine as mod
    monkeypatch.setattr(mod, "reload_env", lambda *a, **k: None)
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true" if on else "false")
    monkeypatch.setenv("GREYLINE_LIVE_TRADING_ENABLED", "false")


# ---- the classifier: opens are gated, exits/covers/stops are not ----------------------------------

def test_opening_actions_classified():
    assert _is_opening_order("BUY")
    assert _is_opening_order("BUYTOOPEN")
    assert _is_opening_order("SELLTOOPEN")
    assert _is_opening_order("buytoopen")            # case-insensitive


def test_exits_and_covers_never_gated():
    for a in ("SELL", "SELLTOCLOSE", "BUYTOCLOSE", "BUYTOCOVER"):
        assert not _is_opening_order(a), a           # de-risking must always pass


def test_protective_stop_never_gated():
    # a BUY-side protective stop is defensive, not an "open"
    assert not _is_opening_order("BUY", order_type="StopMarket")


def test_opening_actions_set_is_exactly_three():
    assert set(_OPENING_ACTIONS) == {"BUY", "BUYTOOPEN", "SELLTOOPEN"}


# ---- the master switch ----------------------------------------------------------------------------

def test_master_on_off(monkeypatch):
    _set_master(monkeypatch, True)
    assert _master_execution_on() is True
    _set_master(monkeypatch, False)
    assert _master_execution_on() is False


def test_live_on_counts_as_master_on(monkeypatch):
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "false")
    monkeypatch.setenv("GREYLINE_LIVE_TRADING_ENABLED", "true")
    assert _master_execution_on() is True


# ---- enforcement at place_order (blocked path only — never reaches the network) --------------------

def test_place_order_blocks_equity_buy_when_master_off(monkeypatch):
    _set_master(monkeypatch, False)
    book = TradeStationSimBookingEngine()
    r = _REAL_PLACE_ORDER(book, "QQQM", 5, action="BUY", order_type="Limit", limit_price=300.0)
    assert r["ok"] is False
    assert r["execution_blocked"] is True
    assert r["order_id"] is None
    assert "kill switch" in r["reject_reason"].lower()
    assert r["http_status"] is None                  # rejected before any request went out


def test_place_order_blocks_option_open_when_master_off(monkeypatch):
    _set_master(monkeypatch, False)
    book = TradeStationSimBookingEngine()
    r = _REAL_PLACE_ORDER(book, "ALAB 260828C315", 1, action="BUYTOOPEN", order_type="Limit", limit_price=2.0)
    assert r["ok"] is False and r["execution_blocked"] is True


def test_multileg_blocks_opening_condor_when_master_off(monkeypatch):
    _set_master(monkeypatch, False)
    book = TradeStationSimBookingEngine()
    legs = [{"symbol": "IWM 260828P200", "quantity": 1, "action": "SELLTOOPEN"},
            {"symbol": "IWM 260828P195", "quantity": 1, "action": "BUYTOOPEN"}]
    r = book.place_multileg(legs, order_type="Limit", limit_price=1.0)
    assert r["ok"] is False and r["execution_blocked"] is True
    assert r["legs"] == legs                          # shape preserved for the caller


def test_multileg_closing_condor_is_not_a_kill_switch_open():
    # a spread of only TOCLOSE legs is de-risking -> the classifier says none are opens
    legs = [{"action": "BUYTOCLOSE"}, {"action": "SELLTOCLOSE"}]
    assert not any(_is_opening_order(l["action"]) for l in legs)
