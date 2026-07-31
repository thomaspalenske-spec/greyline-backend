"""When GREYLINE_CONDOR_ATOMIC_ORDER is on, a condor is CLOSED as ONE atomic multi-leg order (all legs
close together or none) — a partial/naked close is impossible. Fully mocked; no network, no real orders.
"""

import json

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as E

# quotes chosen so cost_to_close (sum short mids − sum wing mids) = 0.3 << credit 1.0 → profit-take fires
_Q = {
    "X 261218C110": (0.48, 0.52),   # short call  (mid .50)
    "X 261218C115": (0.33, 0.37),   # wing call   (mid .35)
    "X 261218P90":  (0.48, 0.52),   # short put   (mid .50)
    "X 261218P85":  (0.33, 0.37),   # wing put    (mid .35)
}


class _FakeQuote:
    def get_quote(self, sym):
        b, a = _Q.get(sym, (0.0, 0.0))
        return {"response_json": {"Quotes": [{"Bid": b, "Ask": a}]}}


class _FakeBooking:
    def __init__(self):
        self.multileg, self.single = [], []

    def place_multileg(self, legs, order_type="Limit", limit_price=None, tif="DAY"):
        self.multileg.append({"legs": legs, "limit": limit_price})
        return {"ok": True, "order_id": "MLC-1", "status": "OK"}

    def place_order(self, *a, **k):
        self.single.append((a, k))
        return {"ok": True, "order_id": "S-1"}


def _open_condor():
    return {
        "symbol": "X", "quantity": 1, "status": "OPEN", "expiration": "2026-12-18",
        "credit_per_condor": 1.0, "credit_total": 100.0, "max_loss_total": 400.0,
        "legs": [
            {"symbol": "X 261218C110", "action": "SELLTOOPEN"},
            {"symbol": "X 261218C115", "action": "BUYTOOPEN"},
            {"symbol": "X 261218P90", "action": "SELLTOOPEN"},
            {"symbol": "X 261218P85", "action": "BUYTOOPEN"},
        ],
    }


def _setup(tmp_path, monkeypatch, atomic):
    led = tmp_path / "vrp_ledger.jsonl"
    led.write_text(json.dumps(_open_condor()) + "\n")
    monkeypatch.setattr(E, "LEDGER", led)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_CONDOR_ATOMIC_ORDER", "true" if atomic else "false")
    monkeypatch.setattr("app.services.tradestation_quote_live_engine.TradeStationQuoteLiveEngine",
                        lambda: _FakeQuote())
    monkeypatch.setattr(E, "_short_leg_greeks_map", lambda self, rows: {})   # no gamma-defense trigger
    _set_market(monkeypatch, True)                                           # default: regular session
    fake = _FakeBooking()
    monkeypatch.setattr(E, "_booking", lambda self: fake)
    return led, fake


def _set_market(monkeypatch, is_open):
    monkeypatch.setattr("app.services.market_hours_engine.MarketHoursEngine",
                        lambda: type("M", (), {"status": lambda self: {"is_regular_session": is_open}})())


def test_atomic_close_places_one_multileg_order(tmp_path, monkeypatch):
    led, fake = _setup(tmp_path, monkeypatch, atomic=True)
    res = E().manage_positions(dry_run=False)

    # profit-take fired and closed via ONE multi-leg order; no single-leg orders
    assert any(d["action"] == "CLOSE" for d in res["decisions"])
    assert len(fake.multileg) == 1 and fake.single == []
    legs = fake.multileg[0]["legs"]
    assert len(legs) == 4
    acts = {l["symbol"]: l["action"] for l in legs}
    assert acts["X 261218C110"] == "BUYTOCLOSE" and acts["X 261218P90"] == "BUYTOCLOSE"   # buy back shorts
    assert acts["X 261218C115"] == "SELLTOCLOSE" and acts["X 261218P85"] == "SELLTOCLOSE"  # sell wings

    # ledger row marked CLOSED (fake returned ok for the atomic order)
    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "CLOSED" and row.get("close_reason")


def test_legacy_close_legs_out_when_flag_off(tmp_path, monkeypatch):
    led, fake = _setup(tmp_path, monkeypatch, atomic=False)
    E().manage_positions(dry_run=False)
    # flag off → 4 separate close orders, no multi-leg
    assert fake.multileg == [] and len(fake.single) == 4


class _RejectBooking:
    def place_multileg(self, legs, order_type="Limit", limit_price=None, tif="DAY"):
        return {"ok": False, "order_id": None, "reject_reason": "insufficient BP (test)"}

    def place_order(self, *a, **k):
        raise AssertionError("atomic reject must NOT fall back to legging out")


def test_close_deferred_when_market_closed(tmp_path, monkeypatch):
    led, fake = _setup(tmp_path, monkeypatch, atomic=True)
    _set_market(monkeypatch, False)                                  # market CLOSED (after hours)
    E().manage_positions(dry_run=False)
    # a close was decided but the market is shut → NOTHING placed (no "all routes are closed" reject)
    assert fake.multileg == [] and fake.single == []
    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "OPEN" and row["manager_status"] == "VRP_CONDOR_CLOSE_DEFERRED"


def test_atomic_close_reject_leaves_full_condor_intact(tmp_path, monkeypatch):
    led, _ = _setup(tmp_path, monkeypatch, atomic=True)
    monkeypatch.setattr(E, "_booking", lambda self: _RejectBooking())
    E().manage_positions(dry_run=False)

    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "OPEN"                                    # all-or-none → NOT marked CLOSED
    assert row["manager_status"] == "VRP_CONDOR_CLOSE_REJECTED_INTACT"
    assert "NOT unhedged" in row["manager_status_reason"]             # accurate: full condor intact
    # the reject reason is captured on the attempt for diagnosis
    attempt = row["close_attempts"][-1]
    assert any(l.get("reject_reason") == "insufficient BP (test)" for l in attempt["legs"])
