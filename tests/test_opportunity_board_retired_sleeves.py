"""The opportunity board must not show RETIRED strategies. The condor sleeves (earnings-vol IV-crush, VRP)
were retired 2026-08-04 (the SIM can't price atomic condor closes); a disabled condor sleeve must not
paint the board with 'OFF, would sell if armed' candidates. Momentum stays (kill-switch, not retired)."""

from app.services.unified_opportunity_board_engine import UnifiedOpportunityBoardEngine as B


def _stub(monkeypatch):
    monkeypatch.setattr(B, "_momentum_group", lambda self: {"strategy": "Momentum", "candidates": []})
    monkeypatch.setattr(B, "_earnings_group", lambda self: {"strategy": "Earnings", "candidates": []})
    monkeypatch.setattr(B, "_vrp_group", lambda self: {"strategy": "VRP", "candidates": []})


def test_retired_condor_sleeves_excluded_when_off(monkeypatch):
    _stub(monkeypatch)
    monkeypatch.setenv("GREYLINE_EARNINGS_VOL_ENABLED", "false")
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "false")
    assert [g["strategy"] for g in B().board()["groups"]] == ["Momentum"]


def test_condor_sleeves_shown_when_enabled(monkeypatch):
    _stub(monkeypatch)
    monkeypatch.setenv("GREYLINE_EARNINGS_VOL_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "true")
    assert [g["strategy"] for g in B().board()["groups"]] == ["Momentum", "Earnings", "VRP"]
