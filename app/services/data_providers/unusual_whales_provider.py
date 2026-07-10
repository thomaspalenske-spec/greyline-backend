import os
import requests


class UnusualWhalesProvider:
    BASE_URL = "https://api.unusualwhales.com"

    def __init__(self):
        self.api_key = os.environ["UNUSUAL_WHALES_API_KEY"]
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "GreyLine/1.0",
        })

    def _get(self, path, params=None, allow_forbidden=False):
        r = self.session.get(
            self.BASE_URL + path,
            params=params,
            timeout=20,
        )

        if allow_forbidden and r.status_code == 403:
            return None

        r.raise_for_status()
        return r.json()

    def docs(self):
        r = self.session.get(
            self.BASE_URL + "/docs",
            headers={"Accept": "text/plain"},
            timeout=20,
        )
        r.raise_for_status()
        return r.text

    def openapi(self):
        import yaml

        r = self.session.get(
            self.BASE_URL + "/api/openapi",
            timeout=20,
        )
        r.raise_for_status()
        return yaml.safe_load(r.text)

    def dark_pool(self, ticker):
        return self._get(f"/api/darkpool/{ticker}")

    def recent_dark_pool(self):
        return self._get("/api/darkpool/recent")

    def recent_flow(self, ticker):
        return self._get(f"/api/stock/{ticker}/flow-recent")

    def flow_per_strike(self, ticker):
        return self._get(f"/api/stock/{ticker}/flow-per-strike")

    def net_flow(self):
        return self._get("/api/net-flow/expiry")

    def gex_levels(self, ticker):
        return self._get(f"/api/stock/{ticker}/gex-levels")

    def greek_exposure(self, ticker):
        return self._get(f"/api/stock/{ticker}/greek-exposure")

    def options_pulse(self, ticker):
        return self._get(
            f"/api/stock/{ticker}/options-pulse",
            allow_forbidden=True,
        )

    def option_chain(self, ticker):
        return self._get(f"/api/stock/{ticker}/option-chains")

    def flow_alerts(self, ticker):
        return self._get(f"/api/stock/{ticker}/flow-alerts")

    def flow_per_expiry(self, ticker):
        return self._get(f"/api/stock/{ticker}/flow-per-expiry")

    def oi_change(self, ticker):
        return self._get(f"/api/stock/{ticker}/oi-change")

    def oi_per_strike(self, ticker):
        return self._get(f"/api/stock/{ticker}/oi-per-strike")

    def variance_risk_premium(self, ticker):
        return self._get(f"/api/stock/{ticker}/volatility/variance-risk-premium")



    def greek_flow(self, symbol, expiry=None):
        path = f"/api/stock/{symbol}/greek-flow"
        if expiry:
            path += f"/{expiry}"
        return self._get(path)

    def spot_exposures(self, symbol):
        return self._get(f"/api/stock/{symbol}/spot-exposures")

    def oi_per_expiry(self, symbol):
        return self._get(f"/api/stock/{symbol}/oi-per-expiry")

    def lit_flow(self, symbol):
        return self._get(f"/api/lit-flow/{symbol}")

    def market_tide(self):
        return self._get("/api/market/market-tide")

    def sector_tide(self, sector):
        return self._get(f"/api/market/{sector}/sector-tide")

    def etf_inflow_outflow(self, ticker):
        return self._get(f"/api/etfs/{ticker}/in-outflow")

    def institutional_ownership(self, ticker):
        return self._get(f"/api/institution/{ticker}/ownership")

    def short_volume(self, ticker):
        return self._get(f"/api/shorts/{ticker}/volume-and-ratio")

    def insider_transactions(self, ticker):
        return self._get(f"/api/insider/{ticker}")

    def congress_trades(self):
        return self._get("/api/congress/recent-trades")
