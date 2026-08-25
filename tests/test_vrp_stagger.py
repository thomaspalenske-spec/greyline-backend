"""VRP entry-stagger + expiry-ladder: space condor entries and ladder expiries so closes land on DISTINCT days
(independent observations for the edge court), accelerating the live proof at the same capital and risk."""

from datetime import datetime, timedelta

from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def test_stagger_gap_env(monkeypatch):
    monkeypatch.setenv("GREYLINE_VRP_STAGGER_ENABLED", "true")
    monkeypatch.delenv("GREYLINE_VRP_MIN_OPEN_GAP_DAYS", raising=False)
    assert V._stagger_gap() == V.STAGGER_MIN_GAP_DAYS
    monkeypatch.setenv("GREYLINE_VRP_MIN_OPEN_GAP_DAYS", "4")
    assert V._stagger_gap() == 4
    monkeypatch.setenv("GREYLINE_VRP_STAGGER_ENABLED", "false")
    assert V._stagger_gap() == 0                       # disabled -> no stagger


def test_trading_days_since():
    today = datetime.utcnow().date()
    assert V._trading_days_since(today.isoformat()) == 0
    # a Monday-to-Friday span is 4 trading days regardless of weekends between
    assert V._trading_days_since("2000-01-01") > 100    # long past -> many trading days


def test_ladder_target_avoids_used_expiry(monkeypatch):
    e = V()
    monkeypatch.setenv("GREYLINE_VRP_STAGGER_ENABLED", "true")
    monkeypatch.setattr(e, "_open_rows", lambda: [{"expiration": "2026-09-18", "status": "OPEN"}])
    import app.services.uw_option_chain_engine as uwm

    def _monthly(target_dte):
        return "2026-09-18" if target_dte <= 40 else "2026-10-16"   # near vs next monthly
    monkeypatch.setattr(uwm.UWOptionChainEngine, "monthly_expiry", staticmethod(_monthly))
    # 09-18 is already open -> the ladder must pick a target landing on the UNUSED 10-16
    t = e._ladder_target()
    assert _monthly(t) == "2026-10-16"


def test_open_defers_when_recent_open(monkeypatch):
    e = V()
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_VRP_STAGGER_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_VRP_MIN_OPEN_GAP_DAYS", "2")
    monkeypatch.setattr(e, "plan", lambda **k: {"planned": [{"symbol": "A"}, {"symbol": "B"}], "skipped": []})
    placed = []
    monkeypatch.setattr(e, "_place_condor_open", lambda con, b: (placed.append(con["symbol"]) or (None, {"skip": "x"})))
    monkeypatch.setattr(e, "_booking", lambda: object())
    # a condor opened TODAY (0 trading days ago) -> DEFER, nothing booked
    monkeypatch.setattr(e, "_open_rows", lambda: [{"opened_at": datetime.utcnow().isoformat(),
                                                   "expiration": "2026-09-18", "status": "OPEN"}])
    r = e.open_positions(dry_run=False)
    assert r.get("stagger_hold") and placed == []


def test_open_caps_to_one_per_cycle(monkeypatch):
    e = V()
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_VRP_STAGGER_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_VRP_MIN_OPEN_GAP_DAYS", "2")
    monkeypatch.setattr(e, "plan", lambda **k: {"planned": [{"symbol": "A", "quantity": 1}, {"symbol": "B", "quantity": 1}, {"symbol": "C", "quantity": 1}], "skipped": []})
    placed = []
    monkeypatch.setattr(e, "_place_condor_open", lambda con, b: (placed.append(con["symbol"]) or (None, {"skip": "x"})))
    monkeypatch.setattr(e, "_booking", lambda: object())
    # last open 9 CALENDAR days ago (>= 2 trading-day gap) -> book, but ONLY ONE this cycle
    monkeypatch.setattr(e, "_open_rows", lambda: [{"opened_at": (datetime.utcnow() - timedelta(days=9)).isoformat(),
                                                   "expiration": "2026-09-18", "status": "OPEN"}])
    e.open_positions(dry_run=False)
    assert placed == ["A"]                             # capped to 1 staggered entry per cycle
