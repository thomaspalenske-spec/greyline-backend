import json
from datetime import datetime
from os import getenv

import requests

from app.services.env_reload import reload_env
from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine


class TradeStationOptionChainLiveEngine:

    def __init__(self):
        reload_env()

    def get_expirations(
        self,
        symbol,
        strike_price=None,
    ):
        TradeStationTokenMaintenanceEngine().evaluate()

        access_token = getenv(
            "TRADESTATION_ACCESS_TOKEN",
            "",
        )
        base_url = getenv(
            "TRADESTATION_SANDBOX_URL",
            "https://api.tradestation.com",
        )
        symbol = (
            symbol
            or ""
        ).upper().strip()

        if not access_token or not symbol:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "symbol": symbol,
                "expiration_lookup_attempted": False,
                "http_status": None,
                "expirations": [],
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": (
                    "OPTION_EXPIRATION_TOKEN_OR_SYMBOL_REQUIRED"
                ),
            }

        url = (
            base_url.rstrip("/")
            + f"/v3/marketdata/options/expirations/{symbol}"
        )

        params = {}

        if strike_price is not None:
            params["strikePrice"] = strike_price

        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "Authorization": (
                        f"Bearer {access_token}"
                    ),
                    "Accept": "application/json",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "symbol": symbol,
                "expiration_lookup_attempted": True,
                "http_status": None,
                "expirations": [],
                "error": str(exc),
                "execution_enabled": False,
                "order_placement_allowed": False,
                "status": (
                    "OPTION_EXPIRATION_LOOKUP_FAILED"
                ),
            }

        try:
            payload = response.json()
        except Exception:
            payload = None

        raw_expirations = []

        if isinstance(payload, dict):
            raw_expirations = (
                payload.get("Expirations")
                or payload.get("expirations")
                or []
            )

        expirations = []

        for item in raw_expirations:
            if isinstance(item, dict):
                value = (
                    item.get("Date")
                    or item.get("date")
                    or item.get("Expiration")
                    or item.get("expiration")
                )
            else:
                value = item

            if value:
                expirations.append(
                    str(value)
                )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "symbol": symbol,
            "expiration_lookup_attempted": True,
            "http_status": response.status_code,
            "expirations": expirations,
            "expiration_count": len(expirations),
            "response_json": payload,
            "response_preview": response.text[:500],
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": (
                "OPTION_EXPIRATIONS_READY"
                if response.status_code == 200
                else "OPTION_EXPIRATION_LOOKUP_FAILED"
            ),
        }

    def get_chain_snapshot(self, symbol, expiration, option_type="All", max_contracts=50):
        TradeStationTokenMaintenanceEngine().evaluate()

        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
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
