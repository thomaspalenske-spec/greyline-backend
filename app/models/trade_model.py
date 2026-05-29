from datetime import datetime
from uuid import uuid4


def create_trade(
    symbol,
    entry_price,
    quantity,
    state="ACTIVE",
    origin="ACTIVE_OPERATIONAL_SIMULATION",
    confidence="SIMULATED"
):
    return {
        "trade_id": f"GL-{uuid4()}",
        "symbol": symbol,
        "state": state,
        "origin": origin,
        "entry_price": entry_price,
        "quantity": quantity,
        "realized_pnl": 0.0,
        "lifecycle_state": "INITIAL_ENTRY",
        "source_classification": confidence,
        "created_timestamp": datetime.utcnow().isoformat(),
        "modified_timestamp": datetime.utcnow().isoformat(),
        "confidence": confidence
    }