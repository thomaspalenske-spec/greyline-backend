"""open_condor_exits() reports the per-open-condor exit price levels (profit-take + hard-stop net
buyback targets + time exit) straight from the ledger — read-only, no quotes, no orders."""

import json

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as E


def test_open_condor_exit_levels(tmp_path, monkeypatch):
    led = tmp_path / "vrp.jsonl"
    led.write_text("\n".join(json.dumps(r) for r in [
        {"symbol": "QQQ", "status": "OPEN", "strategy": "vrp", "expiration": "2026-12-18",
         "quantity": 1, "credit_total": 160.0, "max_loss_total": 340.0,
         "legs": [{"symbol": "QQQ 1C", "action": "SELLTOOPEN"}, {"symbol": "QQQ 2C", "action": "BUYTOOPEN"}]},
        {"symbol": "CLX", "status": "OPEN", "strategy": "earnings_vol", "report_date": "2026-08-03",
         "expiration": "2026-08-21", "quantity": 1, "credit_total": 125.0, "max_loss_total": 375.0, "legs": []},
        {"symbol": "OLD", "status": "CLOSED", "credit_total": 100.0, "max_loss_total": 300.0},
    ]) + "\n")
    monkeypatch.setattr(E, "LEDGER", led)
    # mock ONE broker positions read: QQQ legs net MarketValue −140 → P/L = credit(160) + (−140) = +$20
    class _Book:
        def positions(self):
            return {"response_json": {"Positions": [
                {"Symbol": "QQQ 1C", "MarketValue": -200.0}, {"Symbol": "QQQ 2C", "MarketValue": 60.0}]}}
    monkeypatch.setattr("app.services.tradestation_sim_booking_engine.TradeStationSimBookingEngine", lambda: _Book())

    out = E().open_condor_exits()
    assert out["status"] == "CONDOR_EXITS"
    syms = {c["symbol"]: c for c in out["condors"]}
    assert set(syms) == {"QQQ", "CLX"}          # CLOSED condor excluded

    q = syms["QQQ"]
    assert q["profit_take_buyback"] == 80.0 and q["profit_take_lock"] == 80.0     # 50% of $160 credit
    assert q["hard_stop_buyback"] == round(160.0 + 0.8 * 340.0, 2)               # credit + 80% max loss
    assert q["hard_stop_loss"] == round(0.8 * 340.0, 2)
    assert "DTE" in q["time_exit"]                                                # VRP → DTE liquidation
    # live P/L from the mocked marks: credit 160 + (-200 + 60) = +$20; % = return on max loss (20/340)
    assert q["pnl"] == 20.0 and q["pnl_pct"] == 5.9

    c = syms["CLX"]
    assert c["hard_stop_buyback"] == round(125.0 + 0.8 * 375.0, 2)
    assert "2026-08-03" in c["time_exit"] and "crush" in c["time_exit"]           # earnings → IV-crush exit
    assert c["pnl"] is None                                                       # no marks → null, levels still render
