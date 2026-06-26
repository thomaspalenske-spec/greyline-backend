from datetime import datetime
import json
from pathlib import Path


class HistoricalTradeWarehouseEngine:
    """
    Persistent warehouse for every historical simulation trade.

    GreyLine production engines remain unchanged.
    The simulator adapts to GreyLine.
    """

    def __init__(self):
        self.root = Path("app/data/research")
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, simulation_name: str, trades: list):
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        payload = {
            "simulation": simulation_name,
            "created_at": datetime.utcnow().isoformat(),
            "trade_count": len(trades),
            "trades": trades,
        }

        outfile = self.root / f"{simulation_name}_{ts}.json"

        outfile.write_text(
            json.dumps(payload, indent=2, default=str)
        )

        return {
            "warehouse_file": str(outfile),
            "trade_count": len(trades),
            "status": "HISTORICAL_TRADE_WAREHOUSE_READY",
        }
