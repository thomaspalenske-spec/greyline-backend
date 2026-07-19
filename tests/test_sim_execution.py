import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
from app.services.sim_account_reconciler_engine import SimAccountReconcilerEngine


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


def test_disabled_by_default_places_nothing(monkeypatch):
    monkeypatch.delenv("GREYLINE_SIM_BOOKING_ENABLED", raising=False)
    eng = GreyLineSimExecutionEngine()
    eng.booking = FakeBooking()
    out = eng.book_opens([{"symbol": "AAPL", "side": "BUY", "entry_price": 333.0}], 500)
    assert out["status"] == "SIM_BOOKING_DISABLED"
    assert out["placed"] == 0
    assert eng.booking.calls == []          # no order ever placed while disabled


def test_enabled_places_sized_orders_with_correct_action(monkeypatch):
    # Construct first: TradeStationSimBookingEngine.__init__ does load_dotenv(override=True),
    # so .env would clobber an earlier setenv. Enable AFTER construction; enabled() reads
    # the flag at call time. (In production the flag lives in .env, which is the source.)
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
        def close_position(self, symbol, position_long=None, reason=""):
            self.closes.append(reason); return {"status": "SIM_EXIT_BOOKED"}

    mgr = MomentumExitManagerEngine()
    mgr._sim = FakeSim()
    trade = {"symbol": "AAPL", "side": "BUY", "original_quantity": 100.0, "doctrine_state": {}}
    # TP1 banks 25 of 100 (25%) -> 25% of 8 SIM shares = 2; then STOP closes the rest
    mgr._mirror_exits_to_sim(trade, [{"type": "SCALE", "qty": 25.0, "reason": "TP1"}])
    mgr._mirror_exits_to_sim(trade, [{"type": "CLOSE", "qty": 75.0, "reason": "STOP"}])
    assert mgr._sim.exits == [(2, "TP1")]        # 8 * 0.25 = 2 whole shares
    assert mgr._sim.closes == ["STOP"]           # remainder flattened exactly
    assert trade["doctrine_state"]["sim_shares_original"] == 8.0


def test_reconciler_normalizes_sim_state(monkeypatch):
    eng = SimAccountReconcilerEngine()

    class FakeBook:
        def balances(self):
            return {"ok": True, "response_json": {"Balances": [
                {"AccountID": "SIM123", "Equity": "1000000", "CashBalance": "999500",
                 "BuyingPower": "4000000"}]}}
        def positions(self):
            return {"ok": True, "response_json": {"Positions": [
                {"Symbol": "AAPL", "Quantity": "1", "AveragePrice": "333.0",
                 "MarketValue": "334.0", "UnrealizedProfitLoss": "1.0", "LongShort": "Long"}]}}
        def orders(self):
            return {"ok": True, "response_json": {"Orders": [
                {"OrderID": "1", "StatusDescription": "Received"},   # working
                {"OrderID": "2", "StatusDescription": "Filled"}]}}   # not working
    eng.booking = FakeBook()
    snap = eng.snapshot()
    assert snap["reads_ok"] is True
    assert snap["account_id"] == "SIM123" and snap["equity"] == 1000000.0
    assert snap["position_count"] == 1 and snap["positions"][0]["symbol"] == "AAPL"
    assert snap["working_order_count"] == 1     # only the Received one
