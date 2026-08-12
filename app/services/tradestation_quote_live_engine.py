from datetime import datetime
import json
import time
from os import getenv
import requests

from app.services.env_reload import reload_env
from app.services.http_bounded import bounded_get, envf, KeyedSingleFlight
from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine


def _quote_timeouts():
    # total wall-clock deadline so a trickling TS quote read can't hang the scheduler cycle
    return (envf("GREYLINE_TS_QUOTE_CONNECT_TIMEOUT", 5.0),
            envf("GREYLINE_TS_QUOTE_READ_TIMEOUT", 8.0),
            envf("GREYLINE_TS_QUOTE_DEADLINE", 15.0))


class TradeStationQuoteLiveEngine:
    _quote_cache = {}
    CACHE_TTL_SECONDS = 60
    _SF = KeyedSingleFlight()          # single-flight: concurrent identical quote fetches coalesce

    @classmethod
    def clear_cache(cls):
        cls._quote_cache = {}

    def __init__(self):
        reload_env()

    def get_quotes(self, symbols):
        """BATCH quote: fetch many symbols in ONE TradeStation request — the /v3/marketdata/quotes/
        endpoint accepts a comma-separated symbol list. Returns {UPPER_SYMBOL: result} where each result
        is shaped like get_quote's (response_json.Quotes[0] holds the row), so callers reuse the same
        parsing. Fresh cache hits are served without a network call; ONE token-maintenance check covers the
        whole batch (get_quote does one PER symbol). This turns the condor manager's 16 serial, throttled
        leg-quote round-trips into a single request — the dominant scheduler-cycle cost. Never raises."""
        syms = list(dict.fromkeys(str(s).upper().strip() for s in (symbols or []) if s))
        out, to_fetch, now = {}, [], time.time()
        for s in syms:
            c = self._quote_cache.get(s)
            if c and (now - c.get("_cache_timestamp", 0)) <= self.CACHE_TTL_SECONDS:
                hit = dict(c); hit["cache_hit"] = True
                hit["cache_age_seconds"] = round(now - c.get("_cache_timestamp", 0), 2)  # match single-quote path
                out[s] = hit
            else:
                to_fetch.append(s)
        if not to_fetch:
            return out
        TradeStationTokenMaintenanceEngine().evaluate()          # ONCE for the whole batch, not per symbol
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        if not access_token:
            for s in to_fetch:
                out[s] = {"symbol": s, "status": "ACCESS_TOKEN_OR_SYMBOL_REQUIRED", "response_json": None}
            return out
        # SINGLE-FLIGHT + TOTAL DEADLINE: coalesce concurrent identical batches, and bound the whole read so
        # a trickling TS response can't hang the cycle (requests' timeout is only between-bytes).
        with self._SF.lock(("quotes", tuple(to_fetch))):
            # re-check the cache under the lock — another thread may have just fetched these
            now2 = time.time()
            still = []
            for s in to_fetch:
                c = self._quote_cache.get(s)
                if c and (now2 - c.get("_cache_timestamp", 0)) <= self.CACHE_TTL_SECONDS:
                    hit = dict(c); hit["cache_hit"] = True
                    hit["cache_age_seconds"] = round(now2 - c.get("_cache_timestamp", 0), 2)
                    out[s] = hit
                else:
                    still.append(s)
            if not still:
                return out
            url = base_url.rstrip("/") + "/v3/marketdata/quotes/" + ",".join(still)
            _ct, _rt, _dl = _quote_timeouts()
            try:
                resp, body = bounded_get(requests, url,
                                         headers={"Authorization": f"Bearer {access_token}",
                                                  "Accept": "application/json"},
                                         connect_timeout=_ct, read_timeout=_rt, total_deadline=_dl)
                rj = json.loads(body) if body else None
            except Exception as error:
                for s in still:
                    out[s] = {"symbol": s, "status": "QUOTE_READ_FAILED", "error": str(error)[:120],
                              "response_json": None}
                return out
            by_sym = {str(row.get("Symbol") or "").upper(): row
                      for row in ((rj or {}).get("Quotes") or [])}
            ts = time.time()
            for s in still:
                row = by_sym.get(s)
                res = {"timestamp": datetime.utcnow().isoformat(), "broker": "TradeStation", "symbol": s,
                       "http_status": resp.status_code, "cache_hit": False,
                       "status": "QUOTE_READ_SUCCESS" if row else "QUOTE_READ_FAILED",
                       "response_json": {"Quotes": [row]} if row else None}
                if row:
                    res["_cache_timestamp"] = ts
                    self._quote_cache[s] = dict(res)
                out[s] = res
        return out

    def get_quote(self, symbol):
        maintenance = TradeStationTokenMaintenanceEngine().evaluate()
        access_token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        symbol = symbol.upper().strip()

        if symbol in self._quote_cache:
            cached = dict(self._quote_cache[symbol])

            cache_timestamp = cached.get("_cache_timestamp", 0)
            cache_age_seconds = round(time.time() - cache_timestamp, 2)

            if cache_age_seconds <= self.CACHE_TTL_SECONDS:
                cached["cache_hit"] = True
                cached["cache_age_seconds"] = cache_age_seconds
                return cached

            del self._quote_cache[symbol]

        if not access_token or not symbol:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "symbol": symbol,
                "quote_attempted": False,
                "execution_enabled": False,
                "status": "ACCESS_TOKEN_OR_SYMBOL_REQUIRED"
            }

        url = base_url.rstrip("/") + f"/v3/marketdata/quotes/{symbol}"
        _ct, _rt, _dl = _quote_timeouts()

        # SINGLE-FLIGHT + TOTAL DEADLINE (same as the batch path): coalesce concurrent same-symbol fetches
        # and bound the whole read so a trickling TS response can't hang the cycle.
        with self._SF.lock(("quote", symbol)):
            c = self._quote_cache.get(symbol)                    # re-check under the lock
            if c and (time.time() - c.get("_cache_timestamp", 0)) <= self.CACHE_TTL_SECONDS:
                hit = dict(c); hit["cache_hit"] = True
                hit["cache_age_seconds"] = round(time.time() - c.get("_cache_timestamp", 0), 2)
                return hit

            try:
                response, body = bounded_get(
                    requests, url,
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                    connect_timeout=_ct, read_timeout=_rt, total_deadline=_dl)
            except Exception as error:
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "broker": "TradeStation",
                    "symbol": symbol,
                    "quote_attempted": True,
                    "http_status": None,
                    "execution_enabled": False,
                    "status": "QUOTE_READ_FAILED",
                    "error": str(error)
                }

            try:
                response_json = json.loads(body) if body else None
            except Exception:
                response_json = None

            result = {
                "timestamp": datetime.utcnow().isoformat(),
                "broker": "TradeStation",
                "symbol": symbol,
                "quote_attempted": True,
                "http_status": response.status_code,
                "execution_enabled": False,
                "status": "QUOTE_READ_SUCCESS" if response.status_code == 200 else "QUOTE_READ_FAILED",
                "response_json": response_json,
                "response_preview": (body[:500].decode("utf-8", "replace") if body else ""),
                "cache_hit": False,
            }

            if response.status_code == 200:
                result["_cache_timestamp"] = time.time()
                result["cache_age_seconds"] = 0
                self._quote_cache[symbol] = dict(result)

            return result
