"""Intraday-shadow RTH exemption (2026-08-25): gex/vanna must act on live intraday quotes, so they don't
inherit the full _heavy_blocked RTH defer built for the 164-min chain scans. Default allows them through RTH;
GREYLINE_INTRADAY_SHADOWS_RTH=false restores the old heavy-defer as an escape hatch."""

from app.services.background_scheduler_service import BackgroundSchedulerService as S


def test_default_exempts_intraday_shadows_during_rth(monkeypatch):
    monkeypatch.delenv("GREYLINE_INTRADAY_SHADOWS_RTH", raising=False)
    # heavy block active (RTH) but the light intraday marks are NOT deferred by default
    assert S._intraday_shadow_deferred(True) is False
    # off-hours: nobody is deferred
    assert S._intraday_shadow_deferred(False) is False


def test_escape_hatch_restores_heavy_defer(monkeypatch):
    monkeypatch.setenv("GREYLINE_INTRADAY_SHADOWS_RTH", "false")
    assert S._intraday_shadow_deferred(True) is True     # tracks the heavy gate again
    assert S._intraday_shadow_deferred(False) is False    # still never blocks off-hours
