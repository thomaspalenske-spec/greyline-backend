"""Sector-concentration cap must EXCLUDE defined-risk option legs. Counting a condor's legs at gross
notional (qty x price x 100) massively overstates equity concentration — a ~$500-max-loss SPY condor read
as $10k of BROAD_MARKET, a 2.5x book-wide over-count that falsely tripped MAX_SECTOR and over-blocked new
opens. Options are governed by the VRP sleeve's own risk cap, not this equity limit. Monkeypatched broker
snapshot — no network, no orders."""

import app.services.broker_account_view_engine as bav
from app.services.portfolio_exposure_engine import PortfolioExposureEngine as PX


def _snap(positions):
    return lambda self: {"reads_ok": True, "positions": positions}


def test_option_legs_excluded_only_equity_counts(monkeypatch):
    positions = [
        {"symbol": "IWM", "quantity": 10, "current_price": 120.0, "asset_type": "STOCK"},   # equity -> $1200
        {"symbol": "IWM 260918C200", "quantity": 5, "current_price": 2.0, "asset_type": "OPTION"},  # leg
        {"symbol": "SPY 260918P400", "quantity": 7, "current_price": 3.0},                  # leg (space in symbol)
    ]
    monkeypatch.setattr(bav.BrokerAccountViewEngine, "snapshot", _snap(positions))
    rows, degraded = PX()._broker_positions()
    assert degraded is False
    by = {r["symbol"]: r["notional"] for r in rows}
    assert by == {"IWM": 1200.0}                     # only the IWM equity; the SPY/IWM condor legs excluded


def test_condor_only_underlying_contributes_nothing(monkeypatch):
    # a name held ONLY as condor legs (no equity) must add ZERO to the sector cap — its risk is the
    # defined max loss, capped elsewhere, not gross leg notional.
    positions = [{"symbol": "SPY 260918C805", "quantity": 7, "current_price": 2.0, "asset_type": "OPTION"},
                 {"symbol": "SPY 260918P753", "quantity": 7, "current_price": 4.9, "asset_type": "OPTION"}]
    monkeypatch.setattr(bav.BrokerAccountViewEngine, "snapshot", _snap(positions))
    rows, degraded = PX()._broker_positions()
    assert rows == [] and degraded is False


def test_degraded_read_still_flagged(monkeypatch):
    monkeypatch.setattr(bav.BrokerAccountViewEngine, "snapshot", lambda self: {"reads_ok": False})
    rows, degraded = PX()._broker_positions()
    assert rows == [] and degraded is True           # fail-closed unchanged
