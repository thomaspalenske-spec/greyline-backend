"""Open-window guard on the heavy trend_mf_carry recomputes.

The 5 non-critical recomputes (best-condors card, condor/mf shadows, once-day universe/sector refresh)
do minutes-long serial UW/TS chain work — measured ~164 min, 96% of the whole cycle. If one straddles
the 09:30 open it saturates TradeStation and starves the broker read, failing the exposure gate CLOSED
and blocking the open. `_heavy_recompute_blocked` defers them on trading days from ~05:00 ET through the
16:00 close. These tests pin the window logic WITHOUT running any live cycle."""

from app.services.background_scheduler_service import BackgroundSchedulerService as S


def _mh(market_time, is_weekday=True, is_holiday=False):
    # market_time is an ET-local ISO string, exactly as MarketHoursEngine.status() emits (now_et.isoformat()).
    return {"market_time": market_time, "is_weekday": is_weekday, "is_holiday": is_holiday}


def test_regular_session_is_blocked():
    blocked, reason = S._heavy_recompute_blocked(_mh("2026-08-03T09:35:00-04:00"))
    assert blocked is True and "open-window guard" in reason


def test_just_before_open_is_blocked():
    # 08:00 ET is inside the 05:00-16:00 guard — a heavy scan starting here could still run at 09:30.
    blocked, _ = S._heavy_recompute_blocked(_mh("2026-08-03T08:00:00-04:00"))
    assert blocked is True


def test_early_premarket_before_cutoff_is_allowed():
    # 04:30 ET is before the 05:00 cutoff: a heavy cycle here finishes well before the open, so allow it.
    blocked, _ = S._heavy_recompute_blocked(_mh("2026-08-03T04:30:00-04:00"))
    assert blocked is False


def test_post_close_is_allowed():
    # 16:30 ET post-close — the natural time for shadows / once-day universe refresh.
    blocked, _ = S._heavy_recompute_blocked(_mh("2026-08-03T16:30:00-04:00"))
    assert blocked is False


def test_weekend_is_allowed():
    blocked, _ = S._heavy_recompute_blocked(_mh("2026-08-02T10:00:00-04:00", is_weekday=False))
    assert blocked is False


def test_holiday_is_allowed():
    blocked, _ = S._heavy_recompute_blocked(_mh("2026-07-03T10:00:00-04:00", is_holiday=True))
    assert blocked is False


def test_missing_market_time_fails_open():
    # If the ET clock can't be resolved, ALLOW (never silently freeze the dashboard/forward-tests forever);
    # the broker-read bounded retry is the open-day backstop in that rare case.
    blocked, reason = S._heavy_recompute_blocked({"is_weekday": True, "is_holiday": False})
    assert blocked is False


def test_malformed_input_fails_open():
    blocked, _ = S._heavy_recompute_blocked(None)
    assert blocked is False


def test_env_override_widens_window(monkeypatch):
    # An operator can widen the guard (e.g. 04:00-16:15) via env; verify it is honoured.
    monkeypatch.setenv("GREYLINE_HEAVY_RECOMPUTE_BLOCK_FROM", "04:00")
    monkeypatch.setenv("GREYLINE_HEAVY_RECOMPUTE_BLOCK_UNTIL", "16:15")
    blocked, _ = S._heavy_recompute_blocked(_mh("2026-08-03T04:30:00-04:00"))
    assert blocked is True                       # 04:30 now inside the widened window
    blocked2, _ = S._heavy_recompute_blocked(_mh("2026-08-03T16:10:00-04:00"))
    assert blocked2 is True                       # 16:10 now inside the widened window
