"""End-to-end trace: a VRP condor closed on DOCTRINE (profit-take) records realized_pnl in the ledger,
and the EdgePersistence realized-edge court then counts it as a genuine strategy exit. This is the pipe
that feeds the Edge grade. Fully mocked — no network, no real orders."""

import json

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V
from app.services.edge_persistence_engine import EdgePersistenceEngine as E

# quotes: shorts mid .50, wings mid .35 -> cost_to_close = (.50+.50) - (.35+.35) = 0.30 << credit 1.0
# -> pnl_per = (1.0 - 0.30)*100 = 70; profit-take (>= 50% of credit) fires.
_Q = {
    "X 261218C110": (0.48, 0.52), "X 261218C115": (0.33, 0.37),
    "X 261218P90":  (0.48, 0.52), "X 261218P85":  (0.33, 0.37),
}


class _Quote:
    def get_quote(self, sym):
        b, a = _Q.get(sym, (0.0, 0.0))
        return {"response_json": {"Quotes": [{"Bid": b, "Ask": a}]}}


class _Booking:
    def place_multileg(self, legs, order_type="Limit", limit_price=None, tif="DAY"):
        return {"ok": True, "order_id": "MLC-1", "status": "OK"}   # all legs confirm -> CLOSED


def _open_condor():
    return {"symbol": "X", "quantity": 1, "status": "OPEN", "expiration": "2026-12-18",
            "credit_per_condor": 1.0, "credit_total": 100.0, "max_loss_total": 400.0,
            "legs": [{"symbol": "X 261218C110", "action": "SELLTOOPEN"},
                     {"symbol": "X 261218C115", "action": "BUYTOOPEN"},
                     {"symbol": "X 261218P90", "action": "SELLTOOPEN"},
                     {"symbol": "X 261218P85", "action": "BUYTOOPEN"}]}


def test_doctrine_close_records_realized_and_feeds_the_court(tmp_path, monkeypatch):
    led = tmp_path / "vrp.jsonl"
    led.write_text(json.dumps(_open_condor()) + "\n")
    monkeypatch.setattr(V, "LEDGER", led)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_CONDOR_ATOMIC_ORDER", "true")
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine", lambda: _Quote())
    monkeypatch.setattr(V, "_short_leg_greeks_map", lambda self, rows: {})          # no gamma trigger
    monkeypatch.setattr("app.services.market_hours_engine.MarketHoursEngine",
                        lambda: type("M", (), {"status": lambda self: {"is_regular_session": True}})())
    monkeypatch.setattr(V, "_booking", lambda self: _Booking())

    # --- ACT: run the exit doctrine for real (mocked broker) ---
    res = V().manage_positions(dry_run=False)
    assert any(d.get("action") == "CLOSE" or "PROFIT_TAKE" in str(d) for d in res["decisions"])

    # --- 1) the ledger row is CLOSED on a DOCTRINE reason with realized_pnl priced at the ACTUAL
    #        marketable close debit (not mid): shorts paid at ask (.52+.52), wings sold at bid (.33+.33)
    #        -> net debit 0.38 -> realized (1.0 - 0.38)*100 = 62. Basis is the honest transacted price. ---
    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "CLOSED"
    assert row["close_reason"] == "PROFIT_TAKE_50PCT"                # not a forced/admin close
    assert row["realized_pnl"] == 62.0
    assert row["realized_pnl_basis"] == "close_order"               # marketable close debit, no mid fudge

    # --- 2) the edge court reads it as a genuine strategy exit, NO haircut (basis is honest) ---
    monkeypatch.setattr(E, "VRP_LEDGER", led)
    monkeypatch.setattr(E, "EQ_LEDGER", tmp_path / "none_eq.jsonl")
    monkeypatch.setattr(E, "OPT_LEDGER", tmp_path / "none_opt.jsonl")
    court = E().realized_edge()
    assert court["excluded_forced_closes"] == 0
    prem = court["sleeves"]["premium"]
    assert prem["trades"] == 1
    # 62 net on 400 max-loss = 15.5% return on risk — exact, no haircut
    assert prem["mean_return_on_risk_pct"] == 15.5
    assert "ACCUMULATING (1/20" in prem["verdict"]                   # one real trade toward the gate


class _LegacyBooking:
    """Legacy leg-by-leg close: distinct order per leg, and orders() reports the ACTUAL fills —
    chosen BETTER than the marketable order px so the test proves realized is read from FILLS."""
    FILLS = {"X 261218C110": 0.50, "X 261218P90": 0.50,   # shorts bought back (better than ask .52)
             "X 261218C115": 0.35, "X 261218P85": 0.35}   # wings sold        (better than bid .33)

    def place_order(self, symbol, qty, action="", order_type="Limit", limit_price=None, tif="DAY"):
        return {"ok": True, "order_id": f"L-{symbol}", "status": "OK"}

    def orders(self):
        return {"response_json": {"Orders": [
            {"OrderID": f"L-{s}", "StatusDescription": "Filled", "FilledPrice": p}
            for s, p in self.FILLS.items()]}}


def test_legacy_close_prices_realized_from_actual_fills(tmp_path, monkeypatch):
    led = tmp_path / "vrp.jsonl"
    led.write_text(json.dumps(_open_condor()) + "\n")
    monkeypatch.setattr(V, "LEDGER", led)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_CONDOR_ATOMIC_ORDER", "false")     # legacy leg-by-leg path
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine", lambda: _Quote())
    monkeypatch.setattr(V, "_short_leg_greeks_map", lambda self, rows: {})
    monkeypatch.setattr("app.services.market_hours_engine.MarketHoursEngine",
                        lambda: type("M", (), {"status": lambda self: {"is_regular_session": True}})())
    monkeypatch.setattr(V, "_booking", lambda self: _LegacyBooking())

    V().manage_positions(dry_run=False)
    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "CLOSED" and row["realized_pnl_basis"] == "fills"
    # fill debit = (.50+.50) - (.35+.35) = 0.30 -> realized (1.0 - 0.30)*100 = 70 (from FILLS, not the .38 order px)
    assert row["realized_pnl"] == 70.0


class _AtomicFillBooking:
    """Atomic multi-leg close: one shared order id, and orders() returns the order with per-leg
    ExecutionPrice — the exact SIM shape captured from live order history (Legs[], BuyOrSell)."""
    FILLS = {"X 261218C110": ("Buy", 0.50), "X 261218P90": ("Buy", 0.50),    # buy back shorts
             "X 261218C115": ("Sell", 0.35), "X 261218P85": ("Sell", 0.35)}  # sell wings

    def place_multileg(self, legs, order_type="Limit", limit_price=None, tif="DAY"):
        self._legs = legs
        return {"ok": True, "order_id": "ATOM-1", "status": "OK"}

    def orders(self):
        return {"response_json": {"Orders": [{
            "OrderID": "ATOM-1", "StatusDescription": "Filled", "FilledPrice": "0.30",
            "Legs": [{"Symbol": s, "BuyOrSell": bs, "OpenOrClose": "Close", "ExecutionPrice": px}
                     for s, (bs, px) in self.FILLS.items()]}]}}


def test_atomic_close_prices_realized_from_per_leg_fills(tmp_path, monkeypatch):
    led = tmp_path / "vrp.jsonl"
    led.write_text(json.dumps(_open_condor()) + "\n")
    monkeypatch.setattr(V, "LEDGER", led)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_CONDOR_ATOMIC_ORDER", "true")      # atomic path
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine", lambda: _Quote())
    monkeypatch.setattr(V, "_short_leg_greeks_map", lambda self, rows: {})
    monkeypatch.setattr("app.services.market_hours_engine.MarketHoursEngine",
                        lambda: type("M", (), {"status": lambda self: {"is_regular_session": True}})())
    monkeypatch.setattr(V, "_booking", lambda self: _AtomicFillBooking())

    V().manage_positions(dry_run=False)
    row = json.loads(led.read_text().splitlines()[0])
    # per-leg fills: (.50+.50) buy-back - (.35+.35) wing-sell = 0.30 debit -> realized (1.0-0.30)*100 = 70
    assert row["status"] == "CLOSED" and row["realized_pnl_basis"] == "fills"
    assert row["realized_pnl"] == 70.0
