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
