"""Volatility term-structure carry: the signal, the vol-targeting, and the disaster gates.

Guards the pieces that make this short-vol sleeve survivable: it must go FLAT in backwardation, exit
on the hard stop, size DOWN when vol is high, and never be sized from a ledger count. Uses dry-run /
injected quotes so no real broker order is placed.
"""

from app.services.vol_term_structure_carry_engine import VolTermStructureCarryEngine as V


class FakeQuotes:
    def __init__(self, vix, vix3m, svxy_bid=56.9, svxy_ask=57.1, svxy_last=57.0):
        self.m = {"$VIX.X": {"Last": vix}, "$VIX3M.X": {"Last": vix3m},
                  "SVXY": {"Bid": svxy_bid, "Ask": svxy_ask, "Last": svxy_last}}

    def get_quote(self, sym):
        return {"response_json": {"Quotes": [self.m[sym]]}}


def test_signal_contango_vs_backwardation():
    e = V()
    assert e.signal(FakeQuotes(15, 18))["state"] == "CONTANGO_HARVEST"        # VIX < VIX3M
    assert e.signal(FakeQuotes(30, 22))["state"] == "BACKWARDATION_STAND_ASIDE"  # inverted


def test_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("GREYLINE_VOL_CARRY_ENABLED", raising=False)
    assert V().run_cycle()["status"] == "VOL_CARRY_DISABLED"


def test_after_hours_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_VOL_CARRY_ENABLED", "true")
    assert V().run_cycle(is_regular_session=False)["status"] == "VOL_CARRY_MARKET_CLOSED"


def _plan_with(monkeypatch, vix, vix3m, held=0, avg=0.0, rv=0.20, last=57.0):
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine",
                        lambda: FakeQuotes(vix, vix3m, svxy_last=last, svxy_ask=last, svxy_bid=last))

    class FakePos:
        def get_positions(self):
            ps = [{"Symbol": "SVXY", "AssetType": "STOCK", "Quantity": str(held),
                   "AveragePrice": str(avg)}] if held else []
            return {"response_json": {"Positions": ps}}
    monkeypatch.setattr("app.services.tradestation_positions_live_engine.TradeStationPositionsLiveEngine",
                        lambda: FakePos())
    monkeypatch.setattr(V, "_refresh_bars", lambda self: None)
    monkeypatch.setattr(V, "_realized_vol", lambda self: rv)


def test_backwardation_targets_flat(monkeypatch):
    _plan_with(monkeypatch, vix=30, vix3m=22, held=10, avg=57.0)
    p = V().plan()
    assert p["contango"] is False and p["target_shares"] == 0 and p["delta_shares"] == -10


def test_contango_sizes_by_vol_target(monkeypatch):
    # rv=0.24 -> weight 0.12/0.24 = 0.5; alloc 2000 -> $1000 -> 17 shares @ $57
    _plan_with(monkeypatch, vix=15, vix3m=18, held=0, rv=0.24, last=57.0)
    p = V().plan()
    assert p["contango"] is True
    assert abs(p["target_weight"] - 0.5) < 1e-6
    assert p["target_shares"] == int(0.5 * 2000 // 57)


def test_hard_stop_forces_exit(monkeypatch):
    # held at avg 70, price 57 -> -18.6% <= -15% stop -> flat despite contango
    _plan_with(monkeypatch, vix=15, vix3m=18, held=20, avg=70.0, last=57.0)
    p = V().plan()
    assert p["stopped"] is True and p["target_shares"] == 0


def test_refresh_bars_merges_never_shrinks_archive(monkeypatch, tmp_path):
    """A refresh fetches only recent bars — it must MERGE them into the full-history archive, never
    overwrite it (the bug that once truncated SVXY from 3,724 bars to 120)."""
    hist = tmp_path / "SVXY_daily.csv"
    with open(hist, "w") as f:
        f.write("date,open,high,low,close,volume\n")
        for i in range(40):                                  # 40 old bars in 2019 (< today)
            d = f"2019-{1 + i // 28:02d}-{1 + i % 28:02d}"
            f.write(f"{d},10,11,9,10,1000\n")
    monkeypatch.setattr(V, "HIST", hist)
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "tok")

    class FakeResp:
        status_code = 200
        def json(self):
            return {"Bars": [{"TimeStamp": f"2026-06-{d:02d}T00:00:00Z", "Open": 50, "High": 51,
                              "Low": 49, "Close": 50, "TotalVolume": 5} for d in range(1, 26)]}
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResp())

    V()._refresh_bars()
    import csv as _csv
    with open(hist) as f:
        rows = list(_csv.DictReader(f))
    dates = {r["date"] for r in rows}
    assert len(rows) == 65                                   # 40 old + 25 new, none lost
    assert "2019-01-01" in dates and "2026-06-01" in dates
