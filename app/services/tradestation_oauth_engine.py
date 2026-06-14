import requests
import time

class TradeStationOAuthEngine:

    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0

    # FIX: required by your bridge
    def get_login_url(self):
        return (
            "https://signin.tradestation.com/authorize"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
        )

    def exchange_code(self, code):

        url = "https://signin.tradestation.com/oauth/token"

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri
        }

        r = requests.post(url, data=data)
        res = r.json()

        self.access_token = res.get("access_token")
        self.refresh_token = res.get("refresh_token")
        self.expires_at = time.time() + int(res.get("expires_in", 0))

        return res

    def refresh(self):

        url = "https://signin.tradestation.com/oauth/token"

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        r = requests.post(url, data=data)
        res = r.json()

        self.access_token = res.get("access_token")
        self.expires_at = time.time() + int(res.get("expires_in", 0))

        return res

    def is_valid(self):
        return self.access_token is not None and time.time() < self.expires_at
