"""place_order must derive success from the RESPONSE BODY, not HTTP 200 — a body-level reject
(TradeStation returns 200 with OrderID '0' + an Error) must report ok=False so it can't be recorded
as a filled position. Plus the ledger void reconciler. No real broker calls."""

from app.services.tradestation_sim_booking_engine import _interpret_order


# ---- the interpreter: the whole fix -------------------------------------------------------

def test_success_valid_order_id():
    ok, oid, reason = _interpret_order(200, {"Orders": [{"OrderID": "286234", "Message": "placed"}]})
    assert ok is True and oid == "286234" and reason is None


def test_body_reject_order_id_zero_is_not_ok():
    # THE bug: HTTP 200 but OrderID '0' + Error -> was recorded as filled; must now be ok=False
    ok, oid, reason = _interpret_order(200, {"Orders": [{"OrderID": "0", "Error": "Failure",
                                                         "Message": "insufficient buying power"}]})
    assert ok is False and oid is None
    assert "insufficient" in reason.lower() or "failure" in reason.lower()


def test_body_reject_error_without_order_id():
    ok, oid, reason = _interpret_order(200, {"Orders": [{"Error": "Rejected", "Message": "bad increment"}]})
    assert ok is False and oid is None and reason


def test_top_level_errors_not_ok():
    ok, oid, reason = _interpret_order(200, {"Errors": [{"Message": "bad symbol"}]})
    assert ok is False and oid is None and reason


def test_http_error_not_ok():
    ok, oid, reason = _interpret_order(400, {"Orders": [{"OrderID": "1"}]})
    assert ok is False and "400" in reason


def test_no_orders_or_bad_body_not_ok():
    assert _interpret_order(200, {"Orders": []})[0] is False
    assert _interpret_order(200, None)[0] is False
    assert _interpret_order(200, {})[0] is False


# ---- the reconciler primitive -------------------------------------------------------------

def test_void_latest_reverts_a_rejected_open_without_booking_pnl(tmp_path, monkeypatch):
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
    e = PaperTradeLedgerEngine()
    monkeypatch.setattr(e, "ledger_file", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(e, "_entry_thesis_snapshot", lambda s: {})

    e.open_trade(symbol="AAA", side="BUY", quantity=5, entry_price=10.0)
    r = e.void_latest("AAA", reason="SIM booking rejected")
    assert r["voided"] is True and r["status"] == "VOIDED_REJECT"

    aaa = [t for t in e._read_all() if t["symbol"] == "AAA"][-1]
    assert aaa["status"] == "VOIDED_REJECT"     # NOT OPEN (drops out of positions) and NOT CLOSED
    assert aaa["realized_pnl"] == 0.0           # never traded -> no P&L booked


def test_void_latest_noop_when_nothing_open(tmp_path, monkeypatch):
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
    e = PaperTradeLedgerEngine()
    monkeypatch.setattr(e, "ledger_file", tmp_path / "ledger.jsonl")
    assert e.void_latest("ZZZ")["voided"] is False
