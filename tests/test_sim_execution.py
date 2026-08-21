import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine


class FakeBooking:
    def __init__(self):
        self.calls = []

    def place_order(self, symbol, qty, action="BUY", order_type="Market", tif="DAY", **k):
        self.calls.append({"symbol": symbol, "qty": qty, "action": action,
                           "order_type": order_type, "tif": tif})
        return {"ok": True, "order_id": f"OID-{symbol}", "http_status": 200}


def test_size_shares_is_whole_share():
    assert GreyLineSimExecutionEngine.size_shares(500, 333.0) == 1     # $500/$333 -> 1
    assert GreyLineSimExecutionEngine.size_shares(500, 12.0) == 41     # $500/$12  -> 41
    assert GreyLineSimExecutionEngine.size_shares(500, 0) == 0         # no price
    assert GreyLineSimExecutionEngine.size_shares(500, 900.0) == 0     # sub-share notional


def test_disabled_flag_places_nothing(monkeypatch):
    # Construct BEFORE clearing the flag: __init__ calls reload_env(), which would refresh
    # the key straight back from .env — and .env now says true, since SIM booking went live
    # on 2026-07-19. The engine reads the flag at call time, so clearing it after
    # construction is what actually exercises the disabled path.
    eng = GreyLineSimExecutionEngine()
    monkeypatch.delenv("GREYLINE_SIM_BOOKING_ENABLED", raising=False)
    eng.booking = FakeBooking()
    out = eng.book_opens([{"symbol": "AAPL", "side": "BUY", "entry_price": 333.0}], 500)
    assert out["status"] == "SIM_BOOKING_DISABLED"
    assert out["placed"] == 0
    assert eng.booking.calls == []          # no order ever placed while disabled


def test_enabled_places_sized_orders_with_correct_action(monkeypatch):
    # Construct first, enable after: __init__ calls reload_env(), which refreshes .env
    # values for anything the process did not export. A monkeypatch.setenv is not in that
    # snapshot, so setting the flag earlier would still be reverted to .env's false here.
    # (An operator's real `export` IS protected — see tests/test_env_precedence.py.)
    eng = GreyLineSimExecutionEngine()
    eng.booking = FakeBooking()
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "true")
    opens = [
        {"symbol": "AAPL", "side": "BUY", "entry_price": 333.0},        # -> 1 share BUY
        {"symbol": "F", "side": "SELL_SHORT", "entry_price": 12.0},     # -> 41 shares SELLSHORT
        {"symbol": "BRKA", "side": "BUY", "entry_price": 900000.0},     # sub-share -> skipped
    ]
    out = eng.book_opens(opens, 500)
    assert out["placed"] == 2
    assert out["skipped_sub_share"] == 1
    calls = {c["symbol"]: c for c in eng.booking.calls}
    assert calls["AAPL"]["qty"] == 1 and calls["AAPL"]["action"] == "BUY"
    assert calls["F"]["qty"] == 41 and calls["F"]["action"] == "SELLSHORT"
    assert calls["AAPL"]["order_type"] == "Market" and calls["AAPL"]["tif"] == "DAY"
    assert "BRKA" not in calls               # never placed


class FakeBookingWithPositions(FakeBooking):
    def __init__(self, qty, long_=True):
        super().__init__()
        self._qty, self._long = qty, long_

    def positions(self):
        return {"ok": True, "response_json": {"Positions": [
            {"Symbol": "AAPL", "Quantity": str(self._qty),
             "LongShort": "Long" if self._long else "Short"}]}}


def test_book_exit_action_and_zero_guard(monkeypatch):
    eng = GreyLineSimExecutionEngine()
    eng.booking = FakeBooking()
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "true")
    assert eng.book_exit("AAPL", 2, position_long=True)["action"] == "SELL"
    assert eng.book_exit("AAPL", 2, position_long=False)["action"] == "BUYTOCOVER"
    assert eng.book_exit("AAPL", 0, position_long=True)["status"] == "SKIPPED_ZERO_SHARES"


def test_close_position_flattens_live_sim_qty(monkeypatch):
    eng = GreyLineSimExecutionEngine()
    eng.booking = FakeBookingWithPositions(4, long_=True)
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "true")
    out = eng.close_position("AAPL")
    assert out["status"] == "SIM_EXIT_BOOKED" and out["shares"] == 4 and out["action"] == "SELL"
    # no SIM position -> nothing to close
    eng.booking = FakeBookingWithPositions(0)
    assert eng.close_position("AAPL")["status"] == "NO_SIM_POSITION"


def test_exit_manager_mirrors_scale_and_close():
    from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine

    class FakeSim:
        def __init__(self):
            self.exits, self.closes = [], []
        def enabled(self):
            return True
        def sim_position(self, symbol):
            return 8.0, True            # 8 whole shares held in SIM
        def book_exit(self, symbol, shares, position_long, reason=""):
            self.exits.append((shares, reason)); return {"shares": shares, "status": "SIM_EXIT_BOOKED"}
        def close_position(self, symbol, position_long=None, reason="", already_booked=0):
            self.closes.append((reason, already_booked)); return {"status": "SIM_EXIT_BOOKED"}

    mgr = MomentumExitManagerEngine()
    mgr._sim = FakeSim()
    trade = {"symbol": "AAPL", "side": "BUY", "original_quantity": 100.0, "doctrine_state": {}}
    # TP1 banks 25 of 100 (25%) -> 25% of 8 SIM shares = 2; then STOP closes the rest.
    # state is the object the caller commits; sim_* bookkeeping accumulates into it across passes.
    st = trade["doctrine_state"]
    mgr._mirror_exits_to_sim(trade, [{"type": "SCALE", "qty": 25.0, "reason": "TP1"}], st)
    mgr._mirror_exits_to_sim(trade, [{"type": "CLOSE", "qty": 75.0, "reason": "STOP"}], st)
    assert mgr._sim.exits == [(2, "TP1")]        # 8 * 0.25 = 2 whole shares
    assert mgr._sim.closes == [("STOP", 0)]      # separate pass: TP1 has settled, nothing in flight
    assert trade["doctrine_state"]["sim_shares_original"] == 8.0


def test_close_nets_out_scales_booked_in_the_same_pass():
    """A gap can cross several TPs and the stop in one decide(). The scale-outs are still
    in flight when CLOSE reads positions(), so the close must not flatten the unreduced
    quantity — that sells more than is held and flips the SIM account short."""
    from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine

    class FakeSim:
        def __init__(self):
            self.orders = []
        def enabled(self):
            return True
        def sim_position(self, symbol):
            return 4.0, True            # live position never updates mid-pass
        def book_exit(self, symbol, shares, position_long, reason=""):
            self.orders.append((shares, reason)); return {"shares": shares, "status": "SIM_EXIT_BOOKED"}
        def close_position(self, symbol, position_long=None, reason="", already_booked=0):
            qty = self.sim_position(symbol)[0] - already_booked
            self.orders.append((qty, reason)); return {"shares": qty, "status": "SIM_EXIT_BOOKED"}

    mgr = MomentumExitManagerEngine()
    mgr._sim = FakeSim()
    trade = {"symbol": "INTC", "side": "BUY", "original_quantity": 4.0, "doctrine_state": {}}
    mgr._mirror_exits_to_sim(trade, [{"type": "SCALE", "qty": 1.0, "reason": "TP1"},
                                     {"type": "SCALE", "qty": 1.0, "reason": "TP2"},
                                     {"type": "CLOSE", "qty": 2.0, "reason": "STOP"}],
                             trade["doctrine_state"])
    assert mgr._sim.orders == [(1, "TP1"), (1, "TP2"), (2.0, "STOP")]
    assert sum(o[0] for o in mgr._sim.orders) == 4.0    # exactly flat, never short


def test_close_position_skips_when_in_flight_exits_cover_the_position(monkeypatch):
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "true")
    eng = GreyLineSimExecutionEngine()
    eng.enabled = lambda: True
    eng.sim_position = lambda symbol: (2.0, True)
    res = eng.close_position("INTC", True, reason="STOP", already_booked=2)
    assert res["status"] == "NO_SIM_POSITION"


def test_scale_sizing_is_cumulative_not_per_slice():
    """Flooring each 25% slice independently threw the remainder away every time: a
    2-share SIM position banked nothing at any target, though the second target covers a
    whole share. Cumulative sizing banks it — and 1-share positions still bank nothing,
    which is a real constraint of a $10k book, not an artifact to round away."""
    from app.services.momentum_exit_manager_engine import MomentumExitManagerEngine

    def bank(sim_shares):
        class FakeSim:
            def __init__(self):
                self.orders = []
            def enabled(self):
                return True
            def sim_position(self, symbol):
                return float(sim_shares), True
            def book_exit(self, symbol, shares, position_long, reason=""):
                if shares <= 0:
                    return {"shares": 0, "status": "SKIPPED_ZERO_SHARES"}
                self.orders.append((shares, reason)); return {"shares": shares, "status": "SIM_EXIT_BOOKED"}
            def close_position(self, symbol, position_long=None, reason="", already_booked=0):
                return {"status": "SIM_EXIT_BOOKED"}

        mgr = MomentumExitManagerEngine()
        mgr._sim = FakeSim()
        trade = {"symbol": "AMZN", "side": "BUY", "original_quantity": 100.0, "doctrine_state": {}}
        for i, tp in enumerate(("TP1", "TP2", "TP3")):        # one target per cycle, as live
            mgr._mirror_exits_to_sim(trade, [{"type": "SCALE", "qty": 25.0, "reason": tp}],
                                     trade["doctrine_state"])
        return mgr._sim.orders

    # 2 shares: 25% floors to 0, but the cumulative 50% at TP2 is a whole share
    assert bank(2) == [(1, "TP2")]
    # 8 shares quarter exactly — one share per target, unchanged
    assert bank(8) == [(2, "TP1"), (2, "TP2"), (2, "TP3")]
    # 1 share cannot be quartered by anyone; the runner keeps it until CLOSE
    assert bank(1) == []


def test_suite_cannot_place_a_real_broker_order():
    """Guard on the guard: the autouse conftest block must actually stop an order.

    Real incident — a test with unmocked booking bought 50 shares each of its fake
    symbols AAA/BBB in the live Paper Trading Account on every suite run.
    """
    import pytest
    from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
    with pytest.raises(AssertionError, match="REAL BROKER ORDER"):
        TradeStationSimBookingEngine().place_order("AAA", 50, action="BUY")
