from app.services.ledger_quarantine_report_engine import (
    LedgerQuarantineReportEngine
)


def endpoint():
    return (
        LedgerQuarantineReportEngine()
        .generate()
    )
