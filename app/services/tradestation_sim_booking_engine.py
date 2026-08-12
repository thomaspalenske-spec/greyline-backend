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

import requests

from app.services.env_reload import reload_env
from app.services.live_order_safety_guard_engine import classify_broker_endpoint

SIM_HOST = "https://sim-api.tradestation.com"   # hardcoded — never TRADESTATION_SANDBOX_URL


class SimBookingSafetyError(RuntimeError):
    """Raised when a booking path is not provably against the simulated account."""


def _safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


def _interpret_order(status_code, payload):
    """True order success from the BODY, not just HTTP 200. TradeStation returns 200 with a per-order
    REJECT in the body — OrderID '0'/absent plus an Error/Message (insufficient BP, bad increment,
    "sell N hold fewer", bad symbol). Treating HTTP 200 as 'filled' records rejected orders as booked
    (condor legs recorded while a wing was rejected -> naked short; exits marking the ledger CLOSED
    over still-held positions; stops 'armed' that aren't). Returns (ok, order_id, reject_reason)."""
    if status_code not in (200, 201):
        return False, None, f"HTTP {status_code}"
    if not isinstance(payload, dict):
        return False, None, "no JSON body"
    if payload.get("Errors"):                          # top-level request/validation errors
        return False, None, str(payload.get("Errors"))[:200]
    orders = payload.get("Orders") or []
    if not orders or not isinstance(orders[0], dict):
        return False, None, "no Orders in response"
    o = orders[0]
    oid = o.get("OrderID")
    valid_id = bool(oid) and str(oid).strip() not in ("", "0")
    if o.get("Error") or not valid_id:
        reason = o.get("Error") or o.get("Message") or "no OrderID returned"
        return False, (str(oid) if valid_id else None), str(reason)[:200]
    return True, str(oid), None


# ---- MASTER EXECUTION KILL SWITCH ----------------------------------------------------------------
# The ONE switch that halts autonomous trading. Historically only momentum + ExecutionGovernor honored
# GREYLINE_PAPER_EXECUTION_ENABLED; trend/low_vol/xs/carry booked straight through place_order and
# ignored it, so flipping the "master" off did NOT stop them (the 2026-08-08 gap). Enforcing it HERE, at
# the single choke point every sleeve routes through, makes it a real kill switch that cannot be bypassed
# by a sleeve that forgot to check its own flag.
#
# Scope: it blocks only orders that OPEN or INCREASE exposure. De-risking ALWAYS passes — closes
# (SELLTOCLOSE/BUYTOCLOSE/BUYTOCOVER), plain equity SELLs, and protective stops are never gated, so an
# operator can always flatten/exit while execution is halted. Semantics mirror ExecutionGovernor
# (paper OR live enabled) so the switch and the governor never disagree.

_OPENING_ACTIONS = ("BUY", "BUYTOOPEN", "SELLTOOPEN")


def _master_execution_on():
    paper = (getenv("GREYLINE_PAPER_EXECUTION_ENABLED", "false") or "").strip().lower() == "true"
    live = (getenv("GREYLINE_LIVE_TRADING_ENABLED", "false") or "").strip().lower() == "true"
    return paper or live


def _is_opening_order(action, order_type=None):
    """True only for orders that OPEN/INCREASE exposure (never a close/cover, never a protective stop)."""
    if str(action or "").upper() not in _OPENING_ACTIONS:
        return False
    if str(order_type or "").lower() == "stopmarket":     # a protective stop is defensive, not an open
        return False
    return True


def _kill_switch_reject(request_desc):
    return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
            "http_status": None, "ok": False, "order_id": None,
            "reject_reason": ("execution disabled — master kill switch "
                              "(GREYLINE_PAPER_EXECUTION_ENABLED=false, live off): opens blocked, "
                              "exits still allowed"),
            "execution_blocked": True, "request": request_desc}


def _daily_loss_halted():
    """True once the mission book breaches its daily-loss HALT limit today — the MissionRiskGovernor writes
    the opens_halted marker on that breach. This is the automated gate the governor deferred ("a future
    gate"); enforcing it HERE at the choke point auto-halts new opens across EVERY sleeve, no per-engine
    change. Fail-OPEN (False) on any error: a rare backstop must not freeze normal trading on a transient
    read glitch, and the operator also gets a CRITICAL page independently. Clears at the next start-of-day."""
    try:
        from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
        return bool(MissionRiskGovernorEngine().opens_halted())
    except Exception:
        return False


def _daily_loss_reject(request_desc):
    return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
            "http_status": None, "ok": False, "order_id": None,
            "reject_reason": ("opens halted — mission book past its daily-loss HALT limit today "
                              "(GREYLINE_DAILY_LOSS_HALT_PCT): new opens blocked, exits still allowed; "
                              "clears at the next start-of-day."),
            "execution_blocked": True, "daily_loss_halted": True, "request": request_desc}


class TradeStationSimBookingEngine:

    def __init__(self):
        reload_env()

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
        reload_env()

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
        payload = _safe_json(resp)
        # a confirm reject is a 200 with top-level Errors — don't call it ok on HTTP 200 alone
        ok = resp.status_code == 200 and isinstance(payload, dict) and not payload.get("Errors")
        reason = None if ok else (str((payload or {}).get("Errors"))[:200]
                                  if isinstance(payload, dict) and payload.get("Errors")
                                  else f"HTTP {resp.status_code}")
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "http_status": resp.status_code, "ok": ok, "reject_reason": reason,
                "request": {k: v for k, v in body.items() if k != "AccountID"},
                "response_json": payload}

    def place_order(self, symbol, quantity, action="BUY", order_type="Market",
                    limit_price=None, stop_price=None, tif="DAY"):
        """Place a real SIMULATED order in the SIM account. Guard runs inside _build_order."""
        # MASTER KILL SWITCH (first — before any sizing/cap logic): an OPENING order is refused when
        # execution is disabled. Exits/covers/stops pass so the book can always be flattened. This is the
        # single choke point that makes GREYLINE_PAPER_EXECUTION_ENABLED a real kill switch for EVERY sleeve.
        if _is_opening_order(action, order_type) and not _master_execution_on():
            return _kill_switch_reject({"Symbol": symbol, "Quantity": quantity,
                                        "action": str(action or "").upper()})
        # DAILY-LOSS HALT: once the book breaches its daily HALT limit, new opens are AUTO-blocked (exits
        # still pass so it can de-risk). Same choke-point pattern as the master switch → applies to every
        # sleeve without per-engine changes; clears at the next start-of-day. Makes the governor's -7% halt
        # a REAL halt, not just a page.
        if _is_opening_order(action, order_type) and _daily_loss_halted():
            return _daily_loss_reject({"Symbol": symbol, "Quantity": quantity,
                                       "action": str(action or "").upper()})
        # HARD BOOK-DEPLOYMENT CAP: no EQUITY BUY may push the book's committed long-equity value past
        # MAX_DEPLOY_FRAC x the mission base — the bulletproof backstop against the 12x over-deployment
        # fault (a stale-`held` delta stacking orders). Independent of any sizing engine; fail-closed on a
        # degraded read. Sells / options / stop orders are never gated. See BookDeploymentCapEngine.
        a = str(action or "").upper()
        is_equity = " " not in str(symbol or "")
        if is_equity and a in ("BUY", "BUYTOOPEN") and str(order_type or "").lower() != "stopmarket":
            try:
                from app.services.book_deployment_cap_engine import BookDeploymentCapEngine
                chk = BookDeploymentCapEngine.check_equity_buy(symbol, quantity, limit_price, self)
            except Exception as e:
                chk = {"allowed": False, "reason": f"book cap check errored — buy blocked (fail-closed): {str(e)[:80]}"}
            if not chk.get("allowed"):
                return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                        "http_status": None, "ok": False, "order_id": None,
                        "reject_reason": chk.get("reason"), "book_cap_blocked": True, "book_cap": chk,
                        "request": {"Symbol": symbol, "Quantity": quantity, "action": a}}
        body = self._build_order(symbol, quantity, action, order_type, limit_price, stop_price, tif)
        resp = self._request("POST", f"{SIM_HOST}/v3/orderexecution/orders", json_body=body)
        payload = _safe_json(resp)
        # ok is derived from the BODY (valid OrderID, no Error) — NOT HTTP 200. A body-level reject
        # now reports ok=False / order_id=None so callers can't record it as a filled position.
        ok, order_id, reject_reason = _interpret_order(resp.status_code, payload)
        if ok:
            # the book just changed — drop the shared positions cache so any same-cycle reader sees the
            # new state rather than a ≤TTL-stale snapshot.
            try:
                from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
                TradeStationPositionsLiveEngine.invalidate()
            except Exception:
                pass
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "http_status": resp.status_code, "ok": ok,
                "order_id": order_id, "reject_reason": reject_reason,
                "request": {k: v for k, v in body.items() if k != "AccountID"},
                "response_json": payload}

    def cancel_order(self, order_id):
        """Cancel a working order in the SIM account. Guard runs first, fail-closed."""
        self._assert_sim()
        resp = self._request("DELETE", f"{SIM_HOST}/v3/orderexecution/orders/{order_id}")
        payload = _safe_json(resp)
        ok = resp.status_code in (200, 201) and not (isinstance(payload, dict) and payload.get("Error"))
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "order_id": order_id, "http_status": resp.status_code, "ok": ok,
                "response_json": payload}

    # ---- ATOMIC multi-leg (spread) orders -----------------------------------------------------
    # A condor placed as 4 SEPARATE limit orders can leg in — a wing's limit rests unfilled while the
    # marketable short fills, leaving a naked short (undefined risk). A single multi-leg order fills all
    # legs together or not at all, eliminating that window. `legs` = [{symbol, quantity, action}, ...].
    def _build_multileg_order(self, legs, order_type, limit_price, tif):
        acct = self._assert_sim()
        body = {
            "AccountID": acct,
            "OrderType": order_type,               # Limit for a defined-net-price spread
            "TimeInForce": {"Duration": tif},
            "Route": "Intelligent",
            "Legs": [{"Symbol": str(l["symbol"]).upper(), "Quantity": str(int(l["quantity"])),
                      "TradeAction": l["action"]} for l in legs],
        }
        if order_type in ("Limit", "StopLimit") and limit_price is not None:
            body["LimitPrice"] = str(limit_price)   # NET price across the legs (credit for a short condor)
        return body

    def place_multileg(self, legs, order_type="Limit", limit_price=None, tif="DAY"):
        """Place ONE atomic multi-leg order (all legs fill together or none). ok is BODY-verified."""
        # MASTER KILL SWITCH: a spread that OPENS a position (any TOOPEN leg — e.g. a condor open) is
        # refused when execution is disabled; a closing spread (all TOCLOSE legs) still passes so open
        # condors can always be unwound.
        if any(_is_opening_order(l.get("action")) for l in (legs or [])) and not _master_execution_on():
            return {**_kill_switch_reject({"legs": legs}), "legs": legs, "limit_price": limit_price}
        # DAILY-LOSS HALT (same as place_order): an opening spread is blocked once the book breaches the
        # daily HALT limit; a closing spread still passes so open condors can always be unwound.
        if any(_is_opening_order(l.get("action")) for l in (legs or [])) and _daily_loss_halted():
            return {**_daily_loss_reject({"legs": legs}), "legs": legs, "limit_price": limit_price}
        body = self._build_multileg_order(legs, order_type, limit_price, tif)
        resp = self._request("POST", f"{SIM_HOST}/v3/orderexecution/orders", json_body=body)
        payload = _safe_json(resp)
        ok, order_id, reject_reason = _interpret_order(resp.status_code, payload)
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "http_status": resp.status_code, "ok": ok, "order_id": order_id,
                "reject_reason": reject_reason, "legs": legs, "limit_price": limit_price,
                "response_json": payload}

    def confirm_multileg(self, legs, order_type="Limit", limit_price=None, tif="DAY"):
        """VALIDATE a multi-leg order (does the SIM accept the spread body / route / BP?) WITHOUT placing
        it — used to verify multi-leg support safely before enabling the atomic path."""
        body = self._build_multileg_order(legs, order_type, limit_price, tif)
        resp = self._request("POST", f"{SIM_HOST}/v3/orderexecution/orderconfirm", json_body=body)
        payload = _safe_json(resp)
        ok = resp.status_code == 200 and isinstance(payload, dict) and not payload.get("Errors")
        reason = None if ok else (str((payload or {}).get("Errors"))[:200]
                                  if isinstance(payload, dict) and payload.get("Errors")
                                  else f"HTTP {resp.status_code}")
        return {"timestamp": datetime.utcnow().isoformat(), "environment": "SANDBOX",
                "http_status": resp.status_code, "ok": ok, "reject_reason": reason,
                "legs": legs, "response_json": payload}
