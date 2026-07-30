"""Visibility for the %-of-equity sleeve budgets — engine decides, this only renders."""

from fastapi import APIRouter

from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine

router = APIRouter()


@router.get("/sleeve-budgets")
def sleeve_budgets():
    """Live per-sleeve dollar budgets derived from %-of-equity, plus the deployable-cash clamp.
    Confirms the book can deploy up to ~100% of available cash when sleeves have opportunities."""
    return SleeveCapitalBudgetEngine.snapshot()
