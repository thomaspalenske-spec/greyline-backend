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

    # --- 1) the ledger row is CLOSED on a DOCTRINE reason with realized_pnl recorded ---
    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "CLOSED"
    assert row["close_reason"] == "PROFIT_TAKE_50PCT"                # not a forced/admin close
    assert row["realized_pnl"] == 70.0                              # (1.0 - 0.30) * 100 * 1

    # --- 2) the edge court reads it as a genuine strategy exit (not excluded) ---
    monkeypatch.setattr(E, "VRP_LEDGER", led)
    monkeypatch.setattr(E, "EQ_LEDGER", tmp_path / "none_eq.jsonl")
    monkeypatch.setattr(E, "OPT_LEDGER", tmp_path / "none_opt.jsonl")
    court = E().realized_edge()
    assert court["excluded_forced_closes"] == 0
    prem = court["sleeves"]["premium"]
    assert prem["trades"] == 1
    # cost-net: 70 realized, haircut 3% of 400 max-loss = 12 -> net 58 on 400 risk = 14.5% return
    assert prem["mean_return_on_risk_pct"] == 14.5
    assert "ACCUMULATING (1/20" in prem["verdict"]                   # one real trade toward the gate
