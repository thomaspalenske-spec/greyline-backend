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


class TradeStationPositionsLiveEngine:

    # SHARED per-cycle positions cache. The scheduler fires 25-40+ positions reads per cycle (each ETF
    # sleeve's _held reads once PER basket symbol, ×N sleeves, + reality-guard ×3 + account/exposure
    # reads + dashboard polling), which triggers TradeStation HTTP 429 rate-limiting — cascading into
    # dashboard flapping, the exposure-gate falling back, and the T-bill sweep aborting (unable to
    # rebalance the over-deployment). A short-TTL cache of the last SUCCESSFUL read collapses that burst
    # to ~1 API call. Only 200s are cached; a 429/failure is never cached and never served (so a real
    # degraded read still surfaces), and the next success refreshes. Keyed by account_id (paper vs live).
    _CACHE = {}                       # {account_id: (monotonic_ts, result_dict)}
    _CACHE_TTL_S_DEFAULT = 15.0

    def __init__(self):
        reload_env()

    @classmethod
    def _ttl(cls):
        try:
            v = getenv("GREYLINE_POSITIONS_CACHE_TTL_S", "")
            return float(v) if str(v).strip() else cls._CACHE_TTL_S_DEFAULT
        except (TypeError, ValueError):
            return cls._CACHE_TTL_S_DEFAULT

    @classmethod
    def invalidate(cls, account_id=None):
        """Drop cached reads (all, or one account). Call after an action that changed the book if a
        caller needs to observe it before the TTL expires."""
        if account_id is None:
            cls._CACHE.clear()
        else:
            cls._CACHE.pop(account_id, None)

    def get_positions(self, bypass_cache=False):
        # bypass_cache: read REST directly, ignoring AND not writing the shared cache. Used by the broker
        # stream engine's cross-check so it can compare its mirror against ground-truth REST without
        # reading back its own stream-warmed cache entry (which would make the check circular).
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
                "positions_attempted": False,
                "execution_enabled": False,
                "account_mode": src.get("mode"),
                "status": src.get("error") or "ACCESS_TOKEN_OR_ACCOUNT_ID_REQUIRED"
            }

        # serve a recent SUCCESSFUL read from the shared cache — avoids the 429-triggering read storm.
        ttl = self._ttl()
        hit = self._CACHE.get(account_id)
        if not bypass_cache and ttl > 0 and hit and (time.monotonic() - hit[0]) < ttl:
            cached = dict(hit[1])                       # shallow copy so a caller can't corrupt the cache
            cached["served_from_cache"] = True
            cached["cache_age_s"] = round(time.monotonic() - hit[0], 2)
            return cached

        url = base_url.rstrip("/") + f"/v3/brokerage/accounts/{account_id}/positions"

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
                "positions_attempted": True, "http_status": None, "execution_enabled": False,
                "account_mode": src.get("mode"), "account_id": account_id, "host_kind": src.get("host_kind"),
                "status": "POSITIONS_READ_FAILED", "error": str(error)[:200], "response_json": None,
                "served_from_cache": False,
            }

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "positions_attempted": True,
            "http_status": response.status_code,
            "execution_enabled": False,
            "account_mode": src.get("mode"),
            "account_id": account_id,
            "host_kind": src.get("host_kind"),
            "status": "POSITIONS_READ_SUCCESS" if response.status_code == 200 else "POSITIONS_READ_FAILED",
            "response_preview": (body[:500].decode("utf-8", "replace") if body else ""),
            "response_json": _safe_json(body),
            "served_from_cache": False,
        }
        # cache ONLY a confirmed-good read. A 429/failure is never cached (so it can't mask a real
        # degraded state) and the next success refreshes the entry.
        if not bypass_cache and ttl > 0 and response.status_code == 200:
            self._CACHE[account_id] = (time.monotonic(), result)
        return result
