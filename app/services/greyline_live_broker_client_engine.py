from os import getenv

import requests
from datetime import datetime

from app.services.live_order_safety_guard_engine import (
    LiveOrderSafetyGuard,
    LiveOrderSafetyError,
    classify_broker_endpoint,
)

class GreyLineLiveBrokerClientEngine:

    def __init__(self, api_key=None, base_url=None, access_token=None):

        self.api_key = api_key
        self.base_url = base_url or "https://api.tradestation.com/v3"
        self.access_token = access_token

    def submit_order(self, symbol, quantity, side, price=None):

        # ------------------------------------------------------------------
        # FAIL-CLOSED LIVE-ORDER INTERLOCK
        # This is the ONLY code path that POSTs a real order to TradeStation,
        # and its base_url defaults to PRODUCTION. It previously fired on
        # nothing more than "has a token" — a live-money landmine. No real
        # order may leave this method unless the operator has explicitly
        # authorized live trading, and never against a PRODUCTION target
        # without a conscious production confirmation. (Simulated/paper
        # trading goes through TradeStationSimBookingEngine, not this class.)
        # ------------------------------------------------------------------
        LiveOrderSafetyGuard().assert_safe_to_place_live_order()
        target_env = classify_broker_endpoint(self.base_url)
        if target_env == "PRODUCTION" and getenv(
            "GREYLINE_LIVE_PRODUCTION_CONFIRMED", "false"
        ).lower() != "true":
            raise LiveOrderSafetyError(
                f"Refusing to POST to PRODUCTION target {self.base_url} "
                "without GREYLINE_LIVE_PRODUCTION_CONFIRMED=true"
            )
        if target_env == "UNKNOWN":
            raise LiveOrderSafetyError(
                f"Refusing to POST to unrecognized broker target {self.base_url}"
            )

        # ----------------------------
        # HARD GATE: OAuth REQUIRED
        # ----------------------------
        if not self.access_token:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "BLOCKED_NO_OAUTH_TOKEN",
                "symbol": symbol
            }

        payload = {
            "Symbol": symbol,
            "Quantity": quantity,
            "TradeAction": side,
            "OrderType": "Market" if price is None else "Limit",
            "LimitPrice": price
        }

        try:
            response = requests.post(
                f"{self.base_url}/orderexecution/orders",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.access_token}"
                },
                timeout=5
            )

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "LIVE_ORDER_SENT",
                "broker_response": response.json(),
                "symbol": symbol
            }

        except Exception as e:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "LIVE_BROKER_ERROR",
                "error": str(e),
                "symbol": symbol
            }
