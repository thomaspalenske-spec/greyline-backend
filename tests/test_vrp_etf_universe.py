"""Liquid-ETF VRP universe restriction: the LIVE sleeve trades liquid ETFs only by default (single-name
condors are dead-on-arrival on retail 4-leg costs — cost screen). Reversible via GREYLINE_VRP_ETF_ONLY;
research/backtest passing explicit names is unaffected."""

import pytest

import app.services.conditional_vrp_forward_panel_engine as pm
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


def _capture_names(monkeypatch):
    # make harvest_candidates raise with the names it received, so we read the universe plan() passed
    # WITHOUT running any of plan()'s downstream broker work.
    monkeypatch.setattr(pm.ConditionalVRPForwardPanelEngine, "harvest_candidates",
                        lambda self, names=None: (_ for _ in ()).throw(AssertionError(repr(names))))


def test_default_is_liquid_etf_only(monkeypatch):
    monkeypatch.delenv("GREYLINE_VRP_ETF_ONLY", raising=False)
    _capture_names(monkeypatch)
    with pytest.raises(AssertionError) as ei:
        V().plan()
    got = str(ei.value)
    assert "SPY" in got and "QQQ" in got and "XLE" in got     # the curated ETF list
    assert "AAPL" not in got and "PLTR" not in got            # no single names


def test_flag_off_uses_full_universe(monkeypatch):
    monkeypatch.setenv("GREYLINE_VRP_ETF_ONLY", "false")
    _capture_names(monkeypatch)
    with pytest.raises(AssertionError) as ei:
        V().plan()
    assert str(ei.value) == "None"        # None -> rich_iv falls back to the full DEFAULT_NAMES universe


def test_explicit_names_bypass_restriction(monkeypatch):
    monkeypatch.delenv("GREYLINE_VRP_ETF_ONLY", raising=False)   # even with ETF-only ON
    _capture_names(monkeypatch)
    with pytest.raises(AssertionError) as ei:
        V().plan(names=["AAPL", "MSFT"])
    assert "AAPL" in str(ei.value)        # an explicit research universe is honoured verbatim
