import json
from datetime import datetime
from os import getenv
from pathlib import Path

import requests
from dotenv import load_dotenv

from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine


class TradeStationOptionChainLiveEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"), override=True)

    def get_chain_snapshot(self, symbol, expiration, option_type="All", max_contracts=50):
        TradeStationTokenMaintenanceEngine().evaluate()

        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://api.tradestation.com")
        symbol = symbol.upper().strip()

        url = (
            base_url.rstrip("/")
            + f"/v3/marketdata/stream/options/chains/{symbol}"
            + f"?expiration={expiration}&optionType={option_type}"
        )

        contracts = []

        with requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.tradestation.streams.v2+json",
            },
            stream=True,
            timeout=20,
        ) as response:
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    row = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if row.get("Legs"):
                    contracts.append(row)
                if len(contracts) >= max_contracts:
                    break

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "symbol": symbol,
            "expiration": expiration,
            "option_type": option_type,
            "contracts_returned": len(contracts),
            "contracts": contracts,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTION_CHAIN_SNAPSHOT_READY" if contracts else "OPTION_CHAIN_SNAPSHOT_EMPTY",
        }
