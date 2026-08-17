"""The exit reconciler turns the exit-pricing projection into measured evidence: realized fill
price vs mid, and vs the naked-market counterfactual (the bid the old behaviour would have hit)."""

import json


def _engine(tmp_path):
    from app.services.options_exit_reconciler_engine import OptionsExitReconcilerEngine
    e = OptionsExitReconcilerEngine()
    e.PENDING = tmp_path / "pending.jsonl"
    e.PANEL = tmp_path / "panel.jsonl"
    return e


def _pending(**kw):
    base = {"order_id": "O1", "option_symbol": "MRNA 260828C60", "contracts": 2,
            "reason": "OPTIONS_TP1", "urgency": "patient", "order_type": "Limit",
            "limit_price": 4.00, "decision_mid": 3.72, "decision_bid": 3.20,
            "decision_ask": 4.25, "quote_source": "tradestation", "forced_market": False}
    base.update(kw)
    return base


def test_records_pending_only_with_order_id(tmp_path):
    e = _engine(tmp_path)
    assert e.record_pending(_pending())["status"] == "EXIT_PENDING_RECORDED"
    assert e.record_pending({"order_id": None})["status"] == "NO_ORDER_ID_NOT_RECORDED"


def test_fill_above_the_bid_is_measured_as_beating_the_market(tmp_path, monkeypatch):
    """A patient TP that fills at 4.00 on a 3.20 bid captured 0.80/contract vs a market sell."""
    e = _engine(tmp_path)
    e.record_pending(_pending())

    import app.services.tradestation_orders_live_engine as ol
    monkeypatch.setattr(ol.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"response_json": {"Orders": [
                            {"OrderID": "O1", "StatusDescription": "Filled",
                             "Legs": [{"ExecutionPrice": "4.00"}]}]}})

    r = e.reconcile()
    assert r["filled"] == 1
    row = [json.loads(l) for l in e.PANEL.read_text().splitlines()][0]
    assert row["filled"] is True and row["fill_price"] == 4.00
    assert row["realized_vs_mid"] == round(4.00 - 3.72, 4)      # sold above mid
    assert row["captured_vs_market"] == round(4.00 - 3.20, 4)   # 0.80 better than a market sell
    assert row["captured_vs_market_usd"] == round(0.80 * 100 * 2, 2)  # x100 x2 contracts = 160.0


def test_dead_order_resolves_as_unfilled_no_price(tmp_path, monkeypatch):
    e = _engine(tmp_path)
    e.record_pending(_pending(order_id="O2"))
    import app.services.tradestation_orders_live_engine as ol
    monkeypatch.setattr(ol.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"response_json": {"Orders": [
                            {"OrderID": "O2", "StatusDescription": "Rejected"}]}})
    e.reconcile()
    row = [json.loads(l) for l in e.PANEL.read_text().splitlines()][0]
    assert row["filled"] is False and row["fill_price"] is None


def test_already_resolved_orders_are_not_double_counted(tmp_path, monkeypatch):
    e = _engine(tmp_path)
    e.record_pending(_pending(order_id="O3"))
    import app.services.tradestation_orders_live_engine as ol
    monkeypatch.setattr(ol.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"response_json": {"Orders": [
                            {"OrderID": "O3", "StatusDescription": "Filled",
                             "Legs": [{"ExecutionPrice": "4.10"}]}]}})
    e.reconcile()
    second = e.reconcile()          # nothing new to resolve
    assert second["status"] == "NO_PENDING_EXIT_ORDERS"
    assert len(e.PANEL.read_text().splitlines()) == 1


def test_working_order_stays_pending(tmp_path, monkeypatch):
    e = _engine(tmp_path)
    e.record_pending(_pending(order_id="O4"))
    import app.services.tradestation_orders_live_engine as ol
    monkeypatch.setattr(ol.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"response_json": {"Orders": [
                            {"OrderID": "O4", "StatusDescription": "Received"}]}})
    r = e.reconcile()
    assert r["still_working"] == 1 and r["resolved_now"] == 0
    assert not e.PANEL.exists() or e.PANEL.read_text().strip() == ""


def test_status_verdict_beats_market_when_positive(tmp_path, monkeypatch):
    e = _engine(tmp_path)
    e.record_pending(_pending())
    import app.services.tradestation_orders_live_engine as ol
    monkeypatch.setattr(ol.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"response_json": {"Orders": [
                            {"OrderID": "O1", "StatusDescription": "Filled",
                             "Legs": [{"ExecutionPrice": "4.00"}]}]}})
    e.reconcile()
    s = e.status()
    assert s["filled_exits_measured"] == 1
    assert s["verdict"] == "EXITS_BEATING_MARKET"
    assert s["total_captured_vs_market_usd"] == 160.0
    assert s["by_urgency"]["patient"]["n"] == 1
