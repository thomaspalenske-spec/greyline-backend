"""
Books trades through TradeStation's SIMULATED (paper) trading environment so the
dashboard reflects real broker-simulated fills — not GreyLine's own in-process math.

Safety is the whole point of this engine, because the surrounding config is a landmine:
  * TRADESTATION_SANDBOX_URL is (misleadingly) set to the PRODUCTION host.
  * TRADESTATION_MARGIN_ACCOUNT_ID is a REAL account.
This engine therefore refuses to read either of those. It hardcodes the sim host and
reads only TRADESTATION_SIM_ACCOUNT_ID, and every order path passes through a
fail-closed guard that requires BOTH:
    (1) the endpoint classifies as SANDBOX, and
    (2) the account id starts with "SIM".
If either is false it raises — it is structurally incapable of touching the real account.
"""

from datetime import datetime
from os import getenv
from pathlib import Path

import requests
from dotenv import load_dotenv

from app.services.live_order_safety_guard_engine import classify_broker_endpoint

SIM_HOST = "https://sim-api.tradestation.com"   # hardcoded — never TRADESTATION_SANDBOX_URL


class SimBookingSafetyError(RuntimeError):
    """Raised when a booking path is not provably against the simulated account."""


def _safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


class TradeStationSimBookingEngine:

    def __init__(self):
        load_dotenv(dotenv_path=Path(".env"), override=True)

    # --- fail-closed guard -------------------------------------------------
    def _account_id(self):
        return getenv("TRADESTATION_SIM_ACCOUNT_ID", "")

    def _assert_sim(self):
        """Prove we are on the sandbox host AND targeting a simulated account. Fail closed."""
        acct = self._account_id()
        env = classify_broker_endpoint(SIM_HOST)
        if env != "SANDBOX":
            raise SimBookingSafetyError(f"Endpoint {SIM_HOST} does not classify SANDBOX (got {env})")
        if not acct or not acct.upper().startswith("SIM"):
            raise SimBookingSafetyError(
                "TRADESTATION_SIM_ACCOUNT_ID is missing or not a SIM account "
                f"(got {acct[:3] + '***' if acct else 'EMPTY'})"
            )
        return acct

    # --- auth --------------------------------------------------------------
    def _headers(self, refreshed=False):
        token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        if not token and not refreshed:
            self._refresh_token()
            return self._headers(refreshed=True)
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _refresh_token(self):
        from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine
        TradeStationTokenRefreshEngine().refresh()
        load_dotenv(dotenv_path=Path(".env"), override=True)

    def _request(self, method, url, json_body=None, _retried=False):
        """HTTP with a single transparent token-refresh retry on 401."""
        resp = requests.request(method, url, headers=self._headers(),
                                json=json_body, timeout=25)
        if resp.status_code == 401 and not _retried:
            self._refresh_token()
            return self._request(method, url, json_body=json_body, _retried=True)
        return resp

    # --- reads (SIM account state) ----------------------------------------
    def _read(self, kind):
        acct = self._assert_sim()
        url = f"{SIM_HOST}/v3/brokerage/accounts/{acct}/{kind}"
        resp = self._request("GET", url)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation", "environment": "SANDBOX", "kind": kind,
            "http_status": resp.status_code,
            "ok": resp.status_code == 200,
            "response_json": _safe_json(resp),
        }

    def balances(self):
        return self._read("balances")

    def positions(self):
        return self._read("positions")

    def orders(self):
        return self._read("orders")

    # --- order payload -----------------------------------------------------
    def _build_order(self, symbol, quantity, action, order_type, limit_price, stop_price, tif):
        """TradeStation v3 order body. AccountID travels in the body, not the path."""
        acct = self._assert_sim()
        body = {
            "AccountID": acct,
            "Symbol": str(symbol).upper(),
            "Quantity": str(int(quantity)),
            "OrderType": order_type,            # Market | Limit | StopMarket | StopLimit
            "TradeAction": action,              # BUY | SELL | BUYTOCOVER | SELLSHORT
            "TimeInForce": {"Duration": tif},   # DAY | GTC | ...
            "Route": "Intelligent",
        }
        if order_type in ("Limit", "StopLimit") and limit_price is not None:
            body["LimitPrice"] = str(limit_price)
        if order_type in ("StopMarket", "StopLimit") and stop_price is not None:
            body["StopPrice"] = str(stop_price)
        return body

    def confirm_order(self, symbol, quantity, action="BUY", order_type="Market",
                      limit_price=None, stop_price=None, tif="DAY"):
        """Validate an order (cost, buying-power, route) WITHOUT placing it."""
        body = self._build_order(symbol, quantity, action, order_type, limit_price, stop_price, tif)
        resp = self._request("POST", f"{SIM_HOST}/v3/orderexecution/orderconfirm", json_body=body)
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "http_status": resp.status_code, "ok": resp.status_code == 200,
                "request": {k: v for k, v in body.items() if k != "AccountID"},
                "response_json": _safe_json(resp)}

    def place_order(self, symbol, quantity, action="BUY", order_type="Market",
                    limit_price=None, stop_price=None, tif="DAY"):
        """Place a real SIMULATED order in the SIM account. Guard runs inside _build_order."""
        body = self._build_order(symbol, quantity, action, order_type, limit_price, stop_price, tif)
        resp = self._request("POST", f"{SIM_HOST}/v3/orderexecution/orders", json_body=body)
        payload = _safe_json(resp)
        order_id = None
        if isinstance(payload, dict):
            orders = payload.get("Orders") or []
            if orders and isinstance(orders[0], dict):
                order_id = orders[0].get("OrderID")
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "http_status": resp.status_code, "ok": resp.status_code in (200, 201),
                "order_id": order_id,
                "request": {k: v for k, v in body.items() if k != "AccountID"},
                "response_json": payload}

    def cancel_order(self, order_id):
        """Cancel a working order in the SIM account. Guard runs first, fail-closed."""
        self._assert_sim()
        resp = self._request("DELETE", f"{SIM_HOST}/v3/orderexecution/orders/{order_id}")
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "order_id": order_id, "http_status": resp.status_code,
                "ok": resp.status_code in (200, 201),
                "response_json": _safe_json(resp)}
