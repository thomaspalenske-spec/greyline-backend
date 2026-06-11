import requests
from datetime import datetime


class GreyLineLiveBrokerClientEngine:

    def __init__(self, api_key=None, base_url=None):

        self.api_key = api_key
        self.base_url = base_url or "https://BROKER_API_NOT_CONFIGURED"

    def submit_order(self, symbol, quantity, side, price=None):

        # ----------------------------
        # SAFETY BLOCK (HARD GUARD)
        # ----------------------------
        if not self.api_key:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "LIVE_BROKER_BLOCKED_NO_API_KEY",
                "symbol": symbol,
                "live": False
            }

        payload = {
            "symbol": symbol,
            "qty": quantity,
            "side": side,
            "type": "market" if price is None else "limit",
            "price": price
        }

        # ----------------------------
        # PLACEHOLDER LIVE REQUEST
        # ----------------------------
        try:
            response = requests.post(
                f"{self.base_url}/orders",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}"
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
