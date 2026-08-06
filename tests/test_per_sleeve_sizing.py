"""Per-sleeve position sizing (GREYLINE_PER_SLEEVE_SIZING) — lets overlapping sleeves (trend ∩
xs_momentum on QQQM/IWM/EFA/DBC/GLDM/TLT) run live without fighting over shared shares.

Sizing sources each sleeve's BROKER-CONFIRMED holding (SleeveTradeLedgerEngine.held_qty — reconciled
from observed broker deltas, drift-immune), and reconcile attributes each sleeve only its SHARE of a
shared symbol (broker total minus what every OTHER sleeve confirmed-holds). Disarmed is byte-identical
to legacy (broker total). No network; ledger files are redirected to tmp; no orders placed."""

import json

from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine as ST
from app.services.sleeve_position_ledger_engine import SleevePositionLedgerEngine as SP


def _ledger(tmp_path, rows):
    p = tmp_path / "sleeve_trade_ledger.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _lot(sleeve, sym, qty, px=300.0):
    return {"kind": "lot", "sleeve": sleeve, "symbol": sym, "qty": qty, "remaining": qty,
            "entry_price": px, "opened_at": "2026-08-05T13:00:00", "status": "OPEN"}


def test_effective_held_disarmed_is_broker_total(monkeypatch):
    monkeypatch.delenv("GREYLINE_PER_SLEEVE_SIZING", raising=False)
    assert SP.effective_held("trend", "QQQM", 7) == 7            # byte-identical legacy


def test_effective_held_armed_uses_confirmed_per_sleeve(monkeypatch, tmp_path):
    monkeypatch.setenv("GREYLINE_PER_SLEEVE_SIZING", "true")
    monkeypatch.setattr(ST, "LEDGER", _ledger(tmp_path, [_lot("trend", "QQQM", 5)]))
    # trend owns 5; xs_momentum owns 0 — even though the broker TOTAL handed in is 5
    assert SP.effective_held("trend", "QQQM", 5) == 5
    assert SP.effective_held("xs_momentum", "QQQM", 5) == 0


def test_reconcile_splits_shared_symbol_by_sleeve_share(monkeypatch, tmp_path):
    monkeypatch.setenv("GREYLINE_PER_SLEEVE_SIZING", "true")
    monkeypatch.setattr(ST, "LEDGER", _ledger(tmp_path, [_lot("trend", "QQQM", 5)]))
    eng = ST()
    # broker total rose to 7 (xs bought 2). xs reconciles its SHARE = 7 - trend(5) = 2, NOT the whole 7.
    eng.reconcile_plan("xs_momentum", [{"symbol": "QQQM", "broker_total": 7, "last": 301}])
    assert eng.held_qty("xs_momentum", "QQQM") == 2
    assert eng.held_qty("trend", "QQQM") == 5                    # trend untouched (no share stolen)
    # trend reconciles with total 7: share = 7 - xs(2) = 5 -> unchanged, does NOT claim xs's 2
    eng.reconcile_plan("trend", [{"symbol": "QQQM", "broker_total": 7, "last": 301}])
    assert eng.held_qty("trend", "QQQM") == 5
    # the sum of sleeve holdings equals the broker total — no double-attribution, no phantom
    assert eng.held_qty("trend", "QQQM") + eng.held_qty("xs_momentum", "QQQM") == 7


def test_xs_buys_own_fresh_shares_never_sells_trends(monkeypatch, tmp_path):
    """The collision this whole feature exists to prevent: with trend holding QQQM and xs targeting it,
    xs sizes delta against its OWN 0 -> a BUY of its own shares, never a SELL of trend's."""
    monkeypatch.setenv("GREYLINE_PER_SLEEVE_SIZING", "true")
    monkeypatch.setattr(ST, "LEDGER", _ledger(tmp_path, [_lot("trend", "QQQM", 5)]))
    broker_total = 5                                            # all trend's
    xs_held = SP.effective_held("xs_momentum", "QQQM", broker_total)
    assert xs_held == 0
    xs_target = 3
    assert xs_target - xs_held == 3                             # +3 => BUY, not a sell of trend's 5
    trend_held = SP.effective_held("trend", "QQQM", broker_total)
    assert trend_held == 5
    assert 5 - trend_held == 0                                  # trend already at its own target -> no churn


def test_reconcile_disarmed_is_legacy_broker_total(monkeypatch, tmp_path):
    monkeypatch.delenv("GREYLINE_PER_SLEEVE_SIZING", raising=False)
    monkeypatch.setattr(ST, "LEDGER", _ledger(tmp_path, []))
    eng = ST()
    eng.reconcile_plan("trend", [{"symbol": "QQQM", "held": 5, "last": 300}])
    assert eng.held_qty("trend", "QQQM") == 5                   # whole broker qty, no share subtraction


def test_held_qty_excluding(monkeypatch, tmp_path):
    monkeypatch.setattr(ST, "LEDGER", _ledger(tmp_path, [_lot("trend", "QQQM", 5), _lot("xs_momentum", "QQQM", 2)]))
    eng = ST()
    assert eng.held_qty_excluding("xs_momentum", "QQQM") == 5   # only trend's
    assert eng.held_qty_excluding("trend", "QQQM") == 2         # only xs's


def test_empty_read_guard_keys_on_broker_total(monkeypatch, tmp_path):
    """When armed, a sleeve's `held` is legitimately 0 for a symbol another sleeve owns. The empty-read
    guard must key on broker_total, so a 0-share (but non-degraded) leg does NOT trip the mass-close skip."""
    monkeypatch.setenv("GREYLINE_PER_SLEEVE_SIZING", "true")
    monkeypatch.setattr(ST, "LEDGER", _ledger(tmp_path, [_lot("xs_momentum", "QQQM", 2)]))
    eng = ST()
    # xs holds 2; broker_total 7 (trend holds 5 more). Not a degraded read -> must reconcile, not skip.
    r = eng.reconcile_plan("xs_momentum", [{"symbol": "QQQM", "held": 0, "broker_total": 7, "last": 301}])
    assert r["status"] == "SLEEVE_LEDGER_RECONCILED"           # NOT SLEEVE_LEDGER_SKIP_EMPTY_READ
