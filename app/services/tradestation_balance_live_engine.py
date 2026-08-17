import json
import time
from datetime import datetime
from os import getenv
import requests
from app.services.env_reload import reload_env
from app.services.http_bounded import bounded_get, envf


def _safe_json(body):
    try:
        return json.loads(body) if body else None
    except Exception:
        return None


class TradeStationBalanceLiveEngine:

    # SHARED balance cache — the same read-storm fix positions already has (see
    # TradeStationPositionsLiveEngine). Balance was UNCACHED, so the reliability core, the money tiles,
    # the commander summary and every money engine each hit /balances FRESH; normal dashboard polling
    # alone rate-limited us (HTTP 429 -> balance_ok=False -> Mission Status YELLOW, the 2026-08-09
    # self-throttle). A short-TTL cache of the last GOOD read (200 WITH a parsed Balances record)
    # collapses that burst to ~1 call. A 429/failure/empty body is NEVER cached and never served, so a
    # real degraded read still surfaces and the next good read refreshes. Keyed by account_id.
    _CACHE = {}                       # {account_id: (monotonic_ts, result_dict)}
    _CACHE_TTL_S_DEFAULT = 15.0

    def __init__(self):
        reload_env()

    @classmethod
    def _ttl(cls):
        try:
            v = getenv("GREYLINE_BALANCE_CACHE_TTL_S", "")
            return float(v) if str(v).strip() else cls._CACHE_TTL_S_DEFAULT
        except (TypeError, ValueError):
            return cls._CACHE_TTL_S_DEFAULT

    @classmethod
    def invalidate(cls, account_id=None):
        """Drop cached balance reads (all, or one account). Call after an action that moved cash if a
        caller must observe it before the TTL expires."""
        if account_id is None:
            cls._CACHE.clear()
        else:
            cls._CACHE.pop(account_id, None)

    def get_balance(self):
        from app.services.tradestation_account_source_engine import TradeStationAccountSourceEngine
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        # WHICH account (paper vs live) is decided by the one selector, not here.
        src = TradeStationAccountSourceEngine().resolve()
        account_id = src.get("account_id")
        base_url = src.get("base_url")

        if not src.get("ok") or not access_token or not account_id:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "balance_attempted": False,
                "execution_enabled": False,
                "account_mode": src.get("mode"),
                "status": src.get("error") or "ACCESS_TOKEN_OR_ACCOUNT_ID_REQUIRED"
            }

        # serve a recent GOOD read from the shared cache — avoids the 429-triggering read storm.
        ttl = self._ttl()
        hit = self._CACHE.get(account_id)
        if ttl > 0 and hit and (time.monotonic() - hit[0]) < ttl:
            cached = dict(hit[1])                        # shallow copy so a caller can't corrupt the cache
            cached["served_from_cache"] = True
            cached["cache_age_s"] = round(time.monotonic() - hit[0], 2)
            return cached

        url = base_url.rstrip("/") + f"/v3/brokerage/accounts/{account_id}/balances"

        # TOTAL-DEADLINE bounded read (full trickle-immunity); any failure -> degraded dict, never a hang.
        try:
            response, body = bounded_get(
                requests, url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                connect_timeout=envf("GREYLINE_TS_BROKER_CONNECT_TIMEOUT", 5.0),
                read_timeout=envf("GREYLINE_TS_BROKER_READ_TIMEOUT", 8.0),
                total_deadline=envf("GREYLINE_TS_BROKER_DEADLINE", 15.0))
        except Exception as error:
            return {
                "timestamp": datetime.utcnow().isoformat(), "broker": "TradeStation",
                "balance_attempted": True, "http_status": None, "execution_enabled": False,
                "account_mode": src.get("mode"), "account_id": account_id, "host_kind": src.get("host_kind"),
                "status": "BALANCE_READ_FAILED", "error": str(error)[:200], "response_json": None,
                "served_from_cache": False,
            }

        payload = _safe_json(body)
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "balance_attempted": True,
            "http_status": response.status_code,
            "execution_enabled": False,
            "account_mode": src.get("mode"),
            "account_id": account_id,
            "host_kind": src.get("host_kind"),
            "status": "BALANCE_READ_SUCCESS" if response.status_code == 200 else "BALANCE_READ_FAILED",
            "response_preview": (body[:500].decode("utf-8", "replace") if body else ""),
            "response_json": payload,
            "served_from_cache": False,
        }
        # cache ONLY a genuinely-good read: 200 AND a parsed Balances record. A 429/failure/empty-body is
        # never cached (so it can't mask a real degraded state), and the next good read refreshes it.
        good_body = isinstance(payload, dict) and bool(payload.get("Balances"))
        if ttl > 0 and response.status_code == 200 and good_body:
            self._CACHE[account_id] = (time.monotonic(), result)
        return result
