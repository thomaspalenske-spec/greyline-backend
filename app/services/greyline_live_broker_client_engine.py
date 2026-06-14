import requests
from datetime import datetime

class GreyLineLiveBrokerClientEngine:

    def __init__(self, api_key=None, base_url=None, access_token=None):

        self.api_key = api_key
        self.base_url = base_url or "https://api.tradestation.com/v3"
        self.access_token = access_token

    def submit_order(self, symbol, quantity, side, price=None):

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
