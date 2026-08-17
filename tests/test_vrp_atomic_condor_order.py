"""When GREYLINE_CONDOR_ATOMIC_ORDER is on, a condor is placed as ONE atomic multi-leg order (all legs
fill together or none) — no naked-leg window. Fully mocked; no network, no real orders.
"""

import json

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as E


def _leg(sym, ask, bid):
    return {"symbol": sym, "ask": ask, "bid": bid}


def _planned_condor():
    return {
        "symbol": "IWM", "quantity": 1, "expiration": "2026-09-18",
        "credit_per_condor": 0.85, "credit_total": 85.0, "max_loss_total": 415.0,
        "legs": {
            "short_call": _leg("IWM 260918C240", 2.0, 1.9),
            "wing_call": _leg("IWM 260918C245", 1.1, 1.0),
            "short_put": _leg("IWM 260918P220", 2.2, 2.1),
            "wing_put": _leg("IWM 260918P215", 1.3, 1.2),
        },
    }


class _FakeBooking:
    def __init__(self):
        self.multileg_calls, self.single_calls = [], []

    def place_multileg(self, legs, order_type="Limit", limit_price=None, tif="DAY"):
        self.multileg_calls.append({"legs": legs, "limit": limit_price})
        return {"ok": True, "order_id": "ML-1", "reject_reason": None}

    def place_order(self, *a, **k):
        self.single_calls.append((a, k))
        return {"ok": True, "order_id": "S-1"}


def _setup(tmp_path, monkeypatch, atomic):
    led = tmp_path / "vrp_ledger.jsonl"
    monkeypatch.setattr(E, "LEDGER", led)
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_CONDOR_ATOMIC_ORDER", "true" if atomic else "false")
    monkeypatch.setattr(E, "plan", lambda self, names=None, limit=None: {"planned": [_planned_condor()]})
    fake = _FakeBooking()
    monkeypatch.setattr(E, "_booking", lambda self: fake)
    return led, fake


def test_atomic_places_one_multileg_order(tmp_path, monkeypatch):
    led, fake = _setup(tmp_path, monkeypatch, atomic=True)
    E().open_positions(dry_run=False)

    # exactly ONE multi-leg order with all four legs; NO single-leg orders
    assert len(fake.multileg_calls) == 1 and fake.single_calls == []
    legs = fake.multileg_calls[0]["legs"]
    assert len(legs) == 4
    actions = {l["symbol"]: l["action"] for l in legs}
    assert actions["IWM 260918C240"] == "SELLTOOPEN" and actions["IWM 260918C245"] == "BUYTOOPEN"
    assert actions["IWM 260918P220"] == "SELLTOOPEN" and actions["IWM 260918P215"] == "BUYTOOPEN"
    assert fake.multileg_calls[0]["limit"] == 0.85          # net credit, tick-rounded

    # ledger recorded the condor with atomic legs
    row = json.loads(led.read_text().splitlines()[0])
    assert row["status"] == "OPEN" and all(l.get("atomic") for l in row["legs"])


def test_legacy_path_still_legs_in_when_flag_off(tmp_path, monkeypatch):
    led, fake = _setup(tmp_path, monkeypatch, atomic=False)
    E().open_positions(dry_run=False)
    # flag off → 4 separate orders, no multi-leg
    assert fake.multileg_calls == [] and len(fake.single_calls) == 4
