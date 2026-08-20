"""Cumulative realized P&L must not lose a closed loss (the broker's daily realized resets nightly).

Verifies: the legacy backfill books exactly once, and the broker daily-realized delta is booked once
per change (never doubled), so the equity reflects real realized losses instead of snapping to $10k.
"""

from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine as E


def _paths(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "DIR", tmp_path)
    monkeypatch.setattr(E, "LEDGER", tmp_path / "realized.jsonl")
    monkeypatch.setattr(E, "STATE", tmp_path / "state.json")
    # Booking is confined to the session window; force it open so these delta-booking tests are clock-independent.
    monkeypatch.setattr(E, "_booking_window_open", staticmethod(lambda et_now: True))


def test_empty_is_zero(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    assert E().cumulative_realized() == 0.0


def test_legacy_backfill_books_once(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    e = E()
    assert e.ensure_legacy_backfill()["status"] == "LEGACY_BACKFILLED"
    assert e.cumulative_realized() == round(E.LEGACY_BACKFILL_USD, 2)
    # re-running does NOT double-book it
    assert e.ensure_legacy_backfill()["status"] == "ALREADY_BACKFILLED"
    assert e.cumulative_realized() == round(E.LEGACY_BACKFILL_USD, 2)


def test_broker_daily_delta_booked_once(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    box = {"v": -50.0}
    monkeypatch.setattr(E, "_broker_daily_realized", lambda self: box["v"])
    e = E()
    assert e.record_from_broker()["booked"] == -50.0        # first read books the day's realized
    assert e.record_from_broker()["booked"] == 0.0          # unchanged daily -> nothing re-booked
    assert e.cumulative_realized() == -50.0
    box["v"] = -80.0                                         # more closed later same day
    assert e.record_from_broker()["booked"] == -30.0        # only the DELTA is booked
    assert e.cumulative_realized() == -80.0


def test_backfill_plus_forward_compose(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    monkeypatch.setattr(E, "_broker_daily_realized", lambda self: -12.0)
    e = E()
    e.ensure_legacy_backfill()
    e.record_from_broker()
    assert e.cumulative_realized() == round(E.LEGACY_BACKFILL_USD - 12.0, 2)


def test_no_broker_figure_is_safe(monkeypatch, tmp_path):
    _paths(monkeypatch, tmp_path)
    monkeypatch.setattr(E, "_broker_daily_realized", lambda self: None)
    assert E().record_from_broker()["status"] == "NO_BROKER_REALIZED"
