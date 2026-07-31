"""The reconciler must AUTO-COMPLETE a naked condor (filled short, unfilled wing), not just alert.

Mirrors the manual fix: cancel the stale wing order + re-buy the wing marketable; last-resort buy-to-close
the short once retries are spent. Fully mocked — no network, no real orders (conftest also hard-blocks
place_order as a backstop).
"""

import json
from pathlib import Path

import app.services.conditional_vrp_short_premium_engine as vrp_mod
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as E


class _FakeBooking:
    def __init__(self):
        self.placed, self.cancelled = [], []

    def cancel_order(self, oid):
        self.cancelled.append(oid)
        return {"ok": True}

    def place_order(self, symbol, quantity, action="BUY", order_type="Market",
                    limit_price=None, stop_price=None, tif="DAY"):
        self.placed.append({"symbol": symbol, "qty": quantity, "action": action, "limit": limit_price})
        return {"ok": True, "order_id": f"NEW-{len(self.placed)}", "reject_reason": None}


class _FakeQuote:
    def get_quote(self, sym):
        return {"response_json": {"Quotes": [{"Ask": 2.85, "Bid": 2.78}]}}


def _naked_condor():
    # call side complete (short C144 filled, wing C145 filled); put SHORT filled, put WING unfilled
    return {
        "symbol": "PLTR", "quantity": 5, "status": "OPEN", "expiration": "2026-08-07",
        "legs": [
            {"symbol": "PLTR 260807C145", "action": "BUYTOOPEN", "order_id": "c-wing"},
            {"symbol": "PLTR 260807P111", "action": "BUYTOOPEN", "order_id": "STALE-PUT-WING"},
            {"symbol": "PLTR 260807C144", "action": "SELLTOOPEN", "order_id": "c-short"},
            {"symbol": "PLTR 260807P112", "action": "SELLTOOPEN", "order_id": "p-short"},
        ],
    }


def _setup(tmp_path, monkeypatch, ledger_row):
    p = tmp_path / "vrp_ledger.jsonl"
    p.write_text(json.dumps(ledger_row) + "\n")
    monkeypatch.setattr(E, "LEDGER", p)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_SIM_BOOKING_ENABLED", "true")
    fake_b = _FakeBooking()
    monkeypatch.setattr(E, "_booking", lambda self: fake_b)
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine",
                        lambda: _FakeQuote())
    # fills: everything filled EXCEPT the long put wing P111
    fills = {"PLTR 260807C145": {"avg": 1.2}, "PLTR 260807C144": {"avg": 1.3},
             "PLTR 260807P112": {"avg": 2.63}}   # P111 absent → unfilled wing
    monkeypatch.setattr(E, "_broker_fills", lambda self: fills)
    return p, fake_b


def test_naked_triggers_wing_rebuy(tmp_path, monkeypatch):
    p, b = _setup(tmp_path, monkeypatch, _naked_condor())
    res = E().reconcile_fills(dry_run=False)

    assert res["naked"] and res["naked"][0]["symbol"] == "PLTR"
    # the stale wing order was cancelled and the wing re-bought marketable (at the 2.85 ask)
    assert "STALE-PUT-WING" in b.cancelled
    rebuys = [o for o in b.placed if o["symbol"] == "PLTR 260807P111" and o["action"] == "BUYTOOPEN"]
    assert len(rebuys) == 1 and rebuys[0]["qty"] == 5 and rebuys[0]["limit"] == 2.85
    # attempt counter advanced on the ledger row
    row = json.loads(p.read_text().splitlines()[0])
    assert row["naked_remediation_attempts"] == 1


def test_disabled_book_only_alerts_never_trades(tmp_path, monkeypatch):
    p, b = _setup(tmp_path, monkeypatch, _naked_condor())
    monkeypatch.setenv("GREYLINE_PAPER_EXECUTION_ENABLED", "false")   # booking not live
    res = E().reconcile_fills(dry_run=False)
    assert res["naked"] and res["naked"][0]["symbol"] == "PLTR"
    assert b.placed == [] and b.cancelled == []                       # detected + flagged, but NO trading


def test_last_resort_covers_short_after_retries_exhausted(tmp_path, monkeypatch):
    row = _naked_condor()
    row["naked_remediation_attempts"] = E.MAX_NAKED_REMEDIATION_ATTEMPTS   # retries spent
    p, b = _setup(tmp_path, monkeypatch, row)
    E().reconcile_fills(dry_run=False)
    # no more wing re-buys; instead buy-to-close the uncovered short put
    covers = [o for o in b.placed if o["action"] == "BUYTOCLOSE" and o["symbol"] == "PLTR 260807P112"]
    assert len(covers) == 1 and covers[0]["qty"] == 5
