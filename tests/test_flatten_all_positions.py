"""Clean-slate flatten: closes the WHOLE book from the live broker size, shorts before longs.

Guards the two ways this could go wrong: firing when it shouldn't (disabled / after hours), and
closing in the wrong order (selling a long before buying back its short = a momentary naked short).
Dry-run is used so the test never places a real broker order (see conftest broker guard).
"""

from app.services.flatten_all_positions_engine import FlattenAllPositionsEngine as F


class FakeBook:
    def __init__(self, positions):
        self._p = positions

    def positions(self):
        return {"response_json": {"Positions": self._p}}

    def orders(self):
        return {"response_json": {"Orders": []}}

    def place_order(self, *a, **k):
        raise AssertionError("flatten test must run dry — no real booking")


class FakeQuotes:
    def get_quote(self, sym):
        return {"response_json": {"Quotes": [{"Bid": 1.00, "Ask": 1.10}]}}


def _patch(monkeypatch, positions):
    monkeypatch.setenv("GREYLINE_FLATTEN_ALL_ENABLED", "true")
    monkeypatch.setattr("app.services.tradestation_sim_booking_engine.TradeStationSimBookingEngine",
                        lambda: FakeBook(positions))
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine",
                        lambda: FakeQuotes())


def test_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("GREYLINE_FLATTEN_ALL_ENABLED", raising=False)
    assert F().run_cycle(is_regular_session=True)["status"] == "FLATTEN_ALL_DISABLED"


def test_after_hours_does_not_fire(monkeypatch):
    _patch(monkeypatch, [{"Symbol": "IWM 260904C311", "Quantity": "-1"}])
    assert F().run_cycle(is_regular_session=False)["status"] == "FLATTEN_ALL_MARKET_CLOSED"


def test_empty_book_is_flat(monkeypatch):
    _patch(monkeypatch, [])
    assert F().run_cycle(is_regular_session=True)["status"] == "FLATTEN_ALL_FLAT"


def test_shorts_close_before_longs_with_right_actions(monkeypatch):
    # a long leg listed FIRST, a short leg second — the engine must still act on the short first
    positions = [
        {"Symbol": "IWM 260904P275", "Quantity": "1"},    # long option  -> SELLTOCLOSE
        {"Symbol": "IWM 260904C311", "Quantity": "-1"},   # short option -> BUYTOCLOSE
    ]
    _patch(monkeypatch, positions)
    acts = F().run_cycle(is_regular_session=True, dry_run=True)["actions"]
    assert acts[0]["symbol"] == "IWM 260904C311" and acts[0]["would"] == "BUYTOCLOSE"
    assert acts[1]["symbol"] == "IWM 260904P275" and acts[1]["would"] == "SELLTOCLOSE"


def test_sizes_from_live_qty_and_handles_stock(monkeypatch):
    positions = [
        {"Symbol": "LQD 260828P105", "Quantity": "-3"},   # short 3 -> BUYTOCLOSE, qty 3
        {"Symbol": "SPY", "Quantity": "10"},              # long stock -> SELL
    ]
    _patch(monkeypatch, positions)
    acts = F().run_cycle(is_regular_session=True, dry_run=True)["actions"]
    by = {a["symbol"]: a for a in acts}
    assert by["LQD 260828P105"]["would"] == "BUYTOCLOSE" and by["LQD 260828P105"]["qty"] == -3
    assert by["SPY"]["would"] == "SELL"
