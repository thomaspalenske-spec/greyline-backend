import json
from pathlib import Path
from fastapi import APIRouter

router = APIRouter()

@router.get("/paper-trade-history")
def paper_trade_history(limit: int = 25):
    audit_file = Path("app/data/audit/immutable_audit_ledger.jsonl")

    if not audit_file.exists():
        return {
            "paper_trade_events_found": False,
            "event_count": 0,
            "events": [],
            "status": "NO_AUDIT_LEDGER_FOUND",
        }

    events = []

    with audit_file.open("r") as f:
        for line in f:
            try:
                event = json.loads(line)
            except Exception:
                continue

            if event.get("event_type") == "PAPER_TRADE_TICKET_CREATED":
                events.append(event)

    events = events[-limit:]

    return {
        "paper_trade_events_found": len(events) > 0,
        "event_count": len(events),
        "events": events,
        "status": "PAPER_TRADE_HISTORY_READY",
    }
