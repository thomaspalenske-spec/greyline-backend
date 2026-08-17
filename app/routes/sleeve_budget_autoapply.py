"""Gated auto-apply of the evidence-based capital allocation. GET is read-only (status + dry-run plan);
apply/revert are POST (they mutate the sleeve budget overrides). The engine is GATED OFF by default."""

from fastapi import APIRouter

from app.services.sleeve_budget_autoapply_engine import SleeveBudgetAutoApplyEngine

router = APIRouter()


@router.get("/sleeve-budget-autoapply")
def sleeve_budget_autoapply_status():
    """READ-ONLY: whether auto-apply is enabled, the active overrides, and a dry-run of the exact capped,
    evidence-only step it WOULD take. Never mutates."""
    return SleeveBudgetAutoApplyEngine().status()


@router.post("/sleeve-budget-autoapply/apply")
def sleeve_budget_autoapply_apply(force: bool = False, plan_token: str = None):
    """Apply one capped step toward the measured allocation. Writes the reversible override file; places no
    order. Three ways to authorize:
      * ?plan_token=<token from GET> — operator-APPROVED: applies ONLY if the token still matches the live
        plan; if evidence shifted since you reviewed it, it REFUSES (AUTOAPPLY_PLAN_CHANGED) so exactly the
        reviewed allocation is what applies. This is the recommended operator flow.
      * ?force=true — deliberate operator apply of whatever the plan is right now (no review binding).
      * neither — no-op unless GREYLINE_ALLOC_AUTOAPPLY_ENABLED (the scheduler's auto path)."""
    return SleeveBudgetAutoApplyEngine().apply(force=force, plan_token=plan_token)


@router.post("/sleeve-budget-autoapply/revert")
def sleeve_budget_autoapply_revert():
    """Full revert: clear the override file so every sleeve falls back to its env/default pct."""
    return SleeveBudgetAutoApplyEngine().revert()
