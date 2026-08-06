"""Trend-following sleeve: the 200-DMA signal, whole-share sizing, and cash-in-downtrend behavior.

Guards the mechanics that make it the crash-resistant diversifier: hold only in an uptrend, step to
cash below the 200-DMA, size whole shares from a slot, and take the held size from the LIVE broker.
Dry-run / injected data so no real order is placed.
"""

import os

from app.services.trend_following_engine import TrendFollowingEngine as T


def _hist(tmp_path, sym, level, n=210):
    """Write n daily closes all at `level` so the 200-SMA ~= level.

    Dates END TODAY so the engine's decision-time staleness gate (refuses bars > 4 days old) passes —
    otherwise a fixed past date would be flagged stale and the sleeve would correctly skip the symbol."""
    from datetime import date, timedelta
    p = tmp_path / f"{sym}_daily.csv"
    last = date.today()
    with open(p, "w") as f:
        f.write("date,open,high,low,close,volume\n")
        for i in range(n):
            d = (last - timedelta(days=(n - 1 - i))).isoformat()
            f.write(f"{d},{level},{level},{level},{level},1000\n")


class FakeQuotes:
    def __init__(self, prices):
        self.p = prices                       # {sym: last}

    def get_quote(self, sym):
        px = self.p.get(sym, 0)
        return {"response_json": {"Quotes": [{"Bid": px, "Ask": px, "Last": px}]}}


class FakePos:
    def __init__(self, held):
        self.h = held                         # {sym: qty}

    def get_positions(self):
        ps = [{"Symbol": s, "AssetType": "STOCK", "Quantity": str(q)} for s, q in self.h.items()]
        return {"response_json": {"Positions": ps}}


def _patch(monkeypatch, tmp_path, prices, held=None):
    monkeypatch.setattr(T, "HIST", tmp_path)
    monkeypatch.setattr(T, "BASKET", ["AAA", "BBB"])
    monkeypatch.setattr(T, "SMA", 200)
    # churn guard reads working orders; here there are none -> clean snapshot so sizing is exercised
    # as before (the guard's blocking-on-degraded-read behaviour has its own dedicated tests).
    monkeypatch.setattr("app.services.in_flight_orders_engine.InFlightOrdersEngine.snapshot",
                        classmethod(lambda cls, booking=None: {"ok": True, "net": {}, "count": 0}))
    # alloc is now %-of-equity via SleeveCapitalBudgetEngine; for deterministic sizing these tests
    # drive it from the GREYLINE_TREND_ALLOC_USD env var they set (the pre-conversion contract).
    monkeypatch.setattr(T, "_alloc", classmethod(lambda cls: float(os.getenv("GREYLINE_TREND_ALLOC_USD", "") or 3000.0)))
    _hist(tmp_path, "AAA", 100)
    _hist(tmp_path, "BBB", 100)
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine",
                        lambda: FakeQuotes(prices))
    monkeypatch.setattr("app.services.tradestation_positions_live_engine.TradeStationPositionsLiveEngine",
                        lambda: FakePos(held or {}))


def test_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("GREYLINE_TREND_ENABLED", raising=False)
    assert T().run_cycle()["status"] == "TREND_DISABLED"


def test_after_hours_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_TREND_ENABLED", "true")
    assert T().run_cycle(is_regular_session=False)["status"] == "TREND_MARKET_CLOSED"


def test_uptrend_holds_downtrend_goes_cash(monkeypatch, tmp_path):
    # AAA above its 200-SMA (~100) -> uptrend/hold; BBB below -> cash
    _patch(monkeypatch, tmp_path, prices={"AAA": 130, "BBB": 70})
    monkeypatch.setenv("GREYLINE_TREND_ALLOC_USD", "3000")   # slot = 1500 per asset
    legs = {l["symbol"]: l for l in T().plan()["legs"]}
    assert legs["AAA"]["uptrend"] is True and legs["AAA"]["target_shares"] == int(1500 // 130)
    assert legs["BBB"]["uptrend"] is False and legs["BBB"]["target_shares"] == 0


def test_downtrend_sells_to_cash_from_live_position(monkeypatch, tmp_path):
    # BBB in downtrend but we HOLD 5 shares -> plan must target 0 and sell all 5 (size from broker)
    _patch(monkeypatch, tmp_path, prices={"AAA": 130, "BBB": 70}, held={"BBB": 5})
    legs = {l["symbol"]: l for l in T().plan()["legs"]}
    assert legs["BBB"]["held"] == 5 and legs["BBB"]["target_shares"] == 0
    assert legs["BBB"]["delta_shares"] == -5


def test_dry_run_places_no_orders_and_lists_actions(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, prices={"AAA": 130, "BBB": 70})
    monkeypatch.setenv("GREYLINE_TREND_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_TREND_ALLOC_USD", "3000")
    r = T().run_cycle(is_regular_session=True, dry_run=True)
    assert r["status"] == "TREND_DRYRUN" and r["acted"] is False
    aaa = [a for a in r["actions"] if a["symbol"] == "AAA"]
    assert aaa and aaa[0]["would"] == "BUY"
