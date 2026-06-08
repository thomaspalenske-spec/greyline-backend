from fastapi import APIRouter

from app.services.immutable_audit_ledger_engine import (
    ImmutableAuditLedgerEngine,
)

router = APIRouter()

@router.get("/audit-ledger")
def audit_ledger():
    return ImmutableAuditLedgerEngine().history()

@router.get("/audit-ledger-summary")
def audit_ledger_summary():
    return ImmutableAuditLedgerEngine().summary()
