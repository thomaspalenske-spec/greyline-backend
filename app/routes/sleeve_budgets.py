"""Visibility for the %-of-equity sleeve budgets — engine decides, this only renders."""

from fastapi import APIRouter

from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine

router = APIRouter()


@router.get("/sleeve-budgets")
def sleeve_budgets():
    """Live per-sleeve dollar budgets derived from %-of-equity, plus the deployable-cash clamp.
    Sleeve targets currently sum to 97% of equity (deliberate ~3% headroom), each further clamped
    to live deployable cash."""
    return SleeveCapitalBudgetEngine.snapshot()


@router.get("/risk-budget-sizing-backtest")
def risk_budget_sizing_backtest():
    """A/B the CURRENT %-of-equity sleeve mix vs the inverse-vol RISK-PARITY mix on the same per-sleeve
    return series (2013+, so it includes the Feb-2018 / Mar-2020 short-vol crashes). Shows whether
    de-concentrating the short-vol sleeve cuts the drawdown/tail — the evidence for whether to flip
    GREYLINE_SLEEVE_RISK_BUDGET on. Conservative (instrument-basket buy-and-hold; live signals blunt the tail)."""
    from app.services.risk_budget_sizing_backtest_engine import RiskBudgetSizingBacktestEngine
    return RiskBudgetSizingBacktestEngine.run()
