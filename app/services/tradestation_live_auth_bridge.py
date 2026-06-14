from app.services.tradestation_oauth_engine import TradeStationOAuthEngine
from app.services.greyline_live_broker_client_engine import GreyLineLiveBrokerClientEngine

class TradeStationLiveAuthBridge:

    def __init__(self, client_id, client_secret, redirect_uri, base_url):
        self.auth = TradeStationOAuthEngine(client_id, client_secret, redirect_uri)
        self.base_url = base_url

        self.broker = None

    def simulate_login(self):
        # Step 1: user visits URL
        return self.auth.get_login_url()

    def set_code(self, code):
        # Step 2: exchange code for token
        token_data = self.auth.exchange_code(code)

        # Step 3: inject into broker
        self.broker = GreyLineLiveBrokerClientEngine(
            access_token=self.auth.access_token,
            base_url=self.base_url
        )

        return {
            "status": "AUTH_COMPLETE",
            "token_received": self.auth.access_token is not None
        }

    def submit_order(self, symbol, qty, side, price=100):
        if not self.broker:
            return {"status": "NOT_AUTHENTICATED"}

        return self.broker.submit_order(symbol, qty, side, price)
