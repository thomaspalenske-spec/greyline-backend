from datetime import datetime
from os import getenv
from pathlib import Path
from dotenv import load_dotenv


class TradeStationEndpointMapEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"))

    def get_endpoint_map(self):
        base_url = getenv("TRADESTATION_SANDBOX_URL", "")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "base_url_present": bool(base_url),
            "execution_enabled": False,
            "read_only_endpoints": {
                "account_discovery": "/v3/brokerage/accounts",
                "account_balances": "/v3/brokerage/accounts/{account_id}/balances",
                "positions": "/v3/brokerage/accounts/{account_id}/positions",
                "orders": "/v3/brokerage/accounts/{account_id}/orders"
            },
            "blocked_endpoints": [
                "order_placement",
                "order_replacement",
                "order_cancellation"
            ],
            "status": "ENDPOINT_MAP_ACTIVE"
        }
