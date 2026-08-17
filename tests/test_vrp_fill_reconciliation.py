"""The VRP ledger must reflect ACTUAL fills, not planned limit prices or unfilled legs.

On 2026-07-27 the recorded credit was the PLANNED limit price ($38) while the real fills netted $47,
and the LQD credit counted a call side that never filled. That made the take-profit, stop, and P&L
run off numbers that didn't match the broker. These lock in: reconcile to fills, count only filled
legs, flag a naked short (filled short with no filled wing), and idempotency.
"""

import json

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def _leg(sym, action):
    return {"symbol": sym, "action": action, "limit": 0.0}


def _row(symbol, qty, legs, credit_total, max_loss_total):
    return {"symbol": symbol, "status": "OPEN", "quantity": qty, "legs": legs,
            "credit_total": credit_total, "credit_per_condor": credit_total / 100 / qty,
            "max_loss_total": max_loss_total, "expiration": "2026-09-04"}


def _setup(monkeypatch, tmp_path, rows, fills):
    led = tmp_path / "vrp.jsonl"
    led.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(V, "LEDGER", led)
    monkeypatch.setattr(V, "_broker_fills", lambda self: fills)
    return led


def _read(led):
    return [json.loads(l) for l in led.read_text().splitlines() if l.strip()]


def test_reconciles_full_condor_to_actual_fills(monkeypatch, tmp_path):
    legs = [_leg("IWM 260904C311", "SELLTOOPEN"), _leg("IWM 260904C313", "BUYTOOPEN"),
            _leg("IWM 260904P275", "BUYTOOPEN"), _leg("IWM 260904P277", "SELLTOOPEN")]
    fills = {"IWM 260904C311": {"avg": 1.71, "long": False}, "IWM 260904C313": {"avg": 1.44, "long": True},
             "IWM 260904P275": {"avg": 2.38, "long": True}, "IWM 260904P277": {"avg": 2.58, "long": False}}
    led = _setup(monkeypatch, tmp_path, [_row("IWM", 1, legs, 38.0, 162.0)], fills)
    r = V().reconcile_fills(dry_run=False)
    assert r["reconciled"] == 1 and r["naked"] == []
    row = _read(led)[0]
    assert row["credit_total"] == 47.0          # real fills, not the planned $38
    assert row["max_loss_total"] == 153.0       # width $2x100 - $47
    assert row["fill_reconciled"] is True
    assert all("fill_price" in lg for lg in row["legs"])


def test_counts_only_filled_legs(monkeypatch, tmp_path):
    # LQD put side filled, call side pending -> credit/risk reflect the put spread ONLY
    legs = [_leg("LQD 260828C109", "SELLTOOPEN"), _leg("LQD 260828C109.5", "BUYTOOPEN"),
            _leg("LQD 260828P104", "BUYTOOPEN"), _leg("LQD 260828P105", "SELLTOOPEN")]
    fills = {"LQD 260828P104": {"avg": 0.25, "long": True}, "LQD 260828P105": {"avg": 0.37, "long": False}}
    led = _setup(monkeypatch, tmp_path, [_row("LQD", 3, legs, 39.0, 261.0)], fills)
    r = V().reconcile_fills(dry_run=False)
    row = _read(led)[0]
    assert row["credit_total"] == 36.0          # (0.37-0.25)*100*3, call side excluded
    assert row["max_loss_total"] == 264.0       # put width $1 x100x3 - $36
    assert row["filled_leg_count"] == 2


def test_flags_naked_short_and_does_not_overwrite(monkeypatch, tmp_path):
    # short put filled, its wing NOT filled -> naked, undefined risk
    legs = [_leg("LQD 260828P105", "SELLTOOPEN"), _leg("LQD 260828P104", "BUYTOOPEN")]
    fills = {"LQD 260828P105": {"avg": 0.37, "long": False}}   # wing P104 absent
    led = _setup(monkeypatch, tmp_path, [_row("LQD", 3, legs, 39.0, 261.0)], fills)
    r = V().reconcile_fills(dry_run=False)
    assert r["naked"] and r["naked"][0]["symbol"] == "LQD"
    row = _read(led)[0]
    assert row.get("naked_exposure") is True
    assert row["credit_total"] == 39.0          # NOT overwritten with a wrong (capped) number
    assert row["max_loss_total"] == 261.0


def test_idempotent(monkeypatch, tmp_path):
    legs = [_leg("IWM 260904C311", "SELLTOOPEN"), _leg("IWM 260904C313", "BUYTOOPEN"),
            _leg("IWM 260904P275", "BUYTOOPEN"), _leg("IWM 260904P277", "SELLTOOPEN")]
    fills = {"IWM 260904C311": {"avg": 1.71, "long": False}, "IWM 260904C313": {"avg": 1.44, "long": True},
             "IWM 260904P275": {"avg": 2.38, "long": True}, "IWM 260904P277": {"avg": 2.58, "long": False}}
    _setup(monkeypatch, tmp_path, [_row("IWM", 1, legs, 38.0, 162.0)], fills)
    V().reconcile_fills(dry_run=False)
    r2 = V().reconcile_fills(dry_run=False)      # already reconciled -> no change
    assert r2["reconciled"] == 0


def test_no_fills_leaves_row_untouched(monkeypatch, tmp_path):
    legs = [_leg("IWM 260904C311", "SELLTOOPEN"), _leg("IWM 260904C313", "BUYTOOPEN")]
    led = _setup(monkeypatch, tmp_path, [_row("IWM", 1, legs, 38.0, 162.0)], {})   # nothing filled
    r = V().reconcile_fills(dry_run=False)
    assert r["reconciled"] == 0
    assert _read(led)[0]["credit_total"] == 38.0
