import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import requests

from app.services.env_reload import reload_env

_MISS = object()   # cache sentinel: distinguishes "absent/stale" from a cached value of None (e.g. a 403)


def _envf(name, default):
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return float(default)

# .env.local layers over .env — the UW key lives in both and the local one wins (see the
# credential trap in f514f1f). Applied in order, later file wins; neither overrides a
# variable the operator actually exported.
reload_env('.env')
reload_env('.env.local')


class UnusualWhalesProvider:
    BASE_URL = "https://api.unusualwhales.com"

    _cache = {}
    _cache_lock = Lock()
    # SINGLE-FLIGHT: at most one in-flight fetch per (path, params) key — concurrent callers for the same
    # key wait here and share the one result instead of stampeding UW (the thundering-herd class that hung
    # the scheduler cycle 2026-08-11). Different keys never block each other.
    _inflight_locks = {}
    _inflight_guard = Lock()
    _usage_lock = Lock()
    _usage_path = Path("app/data/unusual_whales_api_usage.json")

    def __init__(self):
        # Graceful: don't crash on construction when the key is absent (it lives in
        # .env.local and may be missing). A missing key surfaces as a clear, catchable
        # error only when a request is actually attempted (see _get).
        self.api_key = os.getenv("UNUSUAL_WHALES_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "GreyLine/1.0",
        })

    @staticmethod
    def _ttl_for_path(path):
        fast_paths = (
            "/flow-recent",
            "/flow-alerts",
            "/market-tide",
            "/sector-tide",
            "/lit-flow/",
            "/net-flow/",
        )
        medium_paths = (
            "/darkpool/",
            "/gex-levels",
            "/greek-flow",
            "/greek-exposure",
            "/spot-exposures",
            "/flow-per-strike",
            "/flow-per-expiry",
        )
        slow_paths = (
            "/oi-change",
            "/oi-per-strike",
            "/oi-per-expiry",
            "/variance-risk-premium",
            "/ownership",
            "/volume-and-ratio",
            "/insider/",
            "/congress/",
        )

        if any(token in path for token in fast_paths):
            return int(os.getenv("UW_FAST_CACHE_SECONDS", "300"))

        if any(token in path for token in medium_paths):
            return int(os.getenv("UW_MEDIUM_CACHE_SECONDS", "900"))

        if any(token in path for token in slow_paths):
            return int(os.getenv("UW_SLOW_CACHE_SECONDS", "21600"))

        return int(os.getenv("UW_DEFAULT_CACHE_SECONDS", "900"))

    @classmethod
    def _usage_state(cls):
        today = datetime.now(timezone.utc).date().isoformat()

        try:
            state = json.loads(cls._usage_path.read_text())
        except Exception:
            state = {}

        if state.get("date") != today:
            state = {
                "date": today,
                "request_count": 0,
                "blocked_count": 0,
                "cache_hit_count": 0,
            }

        return state

    @classmethod
    def _write_usage_state(cls, state):
        cls._usage_path.parent.mkdir(parents=True, exist_ok=True)
        cls._usage_path.write_text(
            json.dumps(state, indent=2, sort_keys=True)
        )

    @classmethod
    def usage_report(cls):
        with cls._usage_lock:
            state = cls._usage_state()

        configured_limit = int(
            os.getenv("UNUSUAL_WHALES_DAILY_REQUEST_LIMIT", "0")
        )
        provider_limit = int(
            state.get("provider_daily_limit") or 0
        )
        daily_limit = provider_limit or configured_limit
        reserve_pct = float(
            os.getenv("UNUSUAL_WHALES_DAILY_RESERVE_PCT", "15")
        )

        usable_limit = (
            int(daily_limit * (1 - reserve_pct / 100))
            if daily_limit > 0
            else None
        )

        return {
            **state,
            "configured_daily_limit": daily_limit or None,
            "reserve_pct": reserve_pct,
            "usable_daily_limit": usable_limit,
            "remaining_before_reserve": (
                max(0, usable_limit - state["request_count"])
                if usable_limit is not None
                else None
            ),
            "status": "UNUSUAL_WHALES_USAGE_REPORT_READY",
        }

    def _consume_budget(self):
        daily_limit = int(
            os.getenv("UNUSUAL_WHALES_DAILY_REQUEST_LIMIT", "0")
        )
        reserve_pct = float(
            os.getenv("UNUSUAL_WHALES_DAILY_RESERVE_PCT", "15")
        )

        with self._usage_lock:
            state = self._usage_state()

            if daily_limit > 0:
                usable_limit = int(
                    daily_limit * (1 - reserve_pct / 100)
                )

                if state["request_count"] >= usable_limit:
                    state["blocked_count"] += 1
                    self._write_usage_state(state)

                    raise RuntimeError(
                        "UNUSUAL_WHALES_DAILY_BUDGET_RESERVED"
                    )

            state["request_count"] += 1
            self._write_usage_state(state)

    def _record_cache_hit(self):
        with self._usage_lock:
            state = self._usage_state()
            state["cache_hit_count"] += 1
            self._write_usage_state(state)

    def _cached_value(self, cache_key, ttl, now):
        """Return the cached value if fresh, else the _MISS sentinel (so a cached None still counts)."""
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached and now - cached["timestamp"] < ttl:
            return cached["value"]
        return _MISS

    @classmethod
    def _key_lock(cls, cache_key):
        """One Lock per cache_key for single-flight coalescing. Soft-capped so the map can't grow without
        bound over a long-lived process (a rare reset only loses coalescing briefly; correctness holds)."""
        with cls._inflight_guard:
            if len(cls._inflight_locks) > 8192:
                cls._inflight_locks.clear()
            lk = cls._inflight_locks.get(cache_key)
            if lk is None:
                lk = Lock()
                cls._inflight_locks[cache_key] = lk
            return lk

    def _bounded_get(self, url, params):
        """GET with a TOTAL wall-clock deadline over the whole request INCLUDING the streamed body read.
        requests' read-timeout is only between-bytes, so a trickling/half-open response never trips it and
        hangs the caller forever (the 2026-08-11 cycle freeze). Stream the body and abort at the deadline.
        Returns (response, body_bytes); the connection is always released."""
        connect_to = _envf("GREYLINE_UW_CONNECT_TIMEOUT", 6.0)
        read_to = _envf("GREYLINE_UW_READ_TIMEOUT", 10.0)
        total = _envf("GREYLINE_UW_TOTAL_DEADLINE", 25.0)
        deadline = time.monotonic() + total
        resp = self.session.get(url, params=params, timeout=(connect_to, read_to), stream=True)
        try:
            chunks = []
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise requests.exceptions.Timeout(
                        f"UW total-request deadline {total:.0f}s exceeded reading body from {url}")
            return resp, b"".join(chunks)
        finally:
            resp.close()

    def _get(
        self,
        path,
        params=None,
        allow_forbidden=False,
        force_refresh=False,
    ):
        normalized_params = tuple(
            sorted((params or {}).items())
        )
        cache_key = (path, normalized_params)
        now = time.time()
        ttl = self._ttl_for_path(path)

        # FAST PATH: a fresh cached value needs neither the lock nor the network.
        if not force_refresh:
            hit = self._cached_value(cache_key, ttl, now)
            if hit is not _MISS:
                self._record_cache_hit()
                return hit

        if not self.api_key:
            raise RuntimeError(
                "UNUSUAL_WHALES_API_KEY not configured (set it in .env.local)."
            )

        # SINGLE-FLIGHT: coalesce concurrent same-key fetches so a burst of callers can't stampede UW.
        with self._key_lock(cache_key):
            # double-check: another thread may have populated the cache while we waited on the lock.
            if not force_refresh:
                hit = self._cached_value(cache_key, ttl, time.time())
                if hit is not _MISS:
                    self._record_cache_hit()
                    return hit

            self._consume_budget()

            response, body = self._bounded_get(self.BASE_URL + path, params)

            if allow_forbidden and response.status_code == 403:
                value = None
            else:
                response.raise_for_status()
                value = json.loads(body) if body else None

            provider_daily_count = response.headers.get(
                "x-uw-daily-req-count"
            )
            provider_daily_limit = response.headers.get(
                "x-uw-token-req-limit"
            )

            return self._finish_get(cache_key, value, provider_daily_count, provider_daily_limit)

    def _finish_get(self, cache_key, value, provider_daily_count, provider_daily_limit):
        with self._usage_lock:
            state = self._usage_state()

            try:
                provider_count = int(provider_daily_count)
            except (TypeError, ValueError):
                provider_count = None

            try:
                provider_limit = int(provider_daily_limit)
            except (TypeError, ValueError):
                provider_limit = None

            if provider_count is not None:
                state["provider_daily_request_count"] = provider_count
                state["request_count"] = max(
                    int(state.get("request_count") or 0),
                    provider_count,
                )

            if provider_limit is not None:
                state["provider_daily_limit"] = provider_limit

            self._write_usage_state(state)

        with self._cache_lock:
            self._cache[cache_key] = {
                "timestamp": time.time(),
                "value": value,
            }

        return value

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

    # Exact paths verified from the live Unusual Whales
    # OpenAPI specification. Observation/research only.
    # These signals are not connected to scoring or execution.
    OBSERVATION_ONLY_ENDPOINTS = {
        "greek_exposure_by_expiry": (
            "/api/stock/{ticker}/"
            "greek-exposure/expiry"
        ),
        "greek_exposure_by_strike": (
            "/api/stock/{ticker}/"
            "greek-exposure/strike"
        ),
        "greek_exposure_by_strike_expiry": (
            "/api/stock/{ticker}/"
            "greek-exposure/strike-expiry"
        ),
        "spot_exposure_expiry_strike": (
            "/api/stock/{ticker}/"
            "spot-exposures/expiry-strike"
        ),
        "spot_exposure_by_strike": (
            "/api/stock/{ticker}/"
            "spot-exposures/strike"
        ),
        "market_oi_change": (
            "/api/market/oi-change"
        ),
        "flow_per_strike_intraday": (
            "/api/stock/{ticker}/"
            "flow-per-strike-intraday"
        ),
        "historical_risk_reversal_skew": (
            "/api/stock/{ticker}/"
            "historical-risk-reversal-skew"
        ),
        "iv_rank": (
            "/api/stock/{ticker}/iv-rank"
        ),
        "volatility_anomaly": (
            "/api/stock/{ticker}/"
            "volatility/anomaly"
        ),
        "volatility_character": (
            "/api/stock/{ticker}/"
            "volatility/character"
        ),
        "volatility_realized": (
            "/api/stock/{ticker}/"
            "volatility/realized"
        ),
        "volatility_stats": (
            "/api/stock/{ticker}/"
            "volatility/stats"
        ),
        "volatility_term_structure": (
            "/api/stock/{ticker}/"
            "volatility/term-structure"
        ),
        "lit_flow_recent": (
            "/api/lit-flow/recent"
        ),
        "etf_exposure": (
            "/api/etfs/{ticker}/exposure"
        ),
        "etf_holdings": (
            "/api/etfs/{ticker}/holdings"
        ),
        "etf_info": (
            "/api/etfs/{ticker}/info"
        ),
        "etf_weights": (
            "/api/etfs/{ticker}/weights"
        ),
        "market_sector_etfs": (
            "/api/market/sector-etfs"
        ),
        "etf_tide": (
            "/api/market/{ticker}/etf-tide"
        ),
        "congress_late_reports": (
            "/api/congress/late-reports"
        ),
        "congress_unusual_trades": (
            "/api/congress/unusual-trades"
        ),
        "insider_transactions_all": (
            "/api/insider/transactions"
        ),
        "insider_ticker_flow": (
            "/api/insider/{ticker}/ticker-flow"
        ),
        "market_insider_buy_sells": (
            "/api/market/insider-buy-sells"
        ),
        "stock_insider_buy_sells": (
            "/api/stock/{ticker}/"
            "insider-buy-sells"
        ),
        "short_data": (
            "/api/shorts/{ticker}/data"
        ),
        "short_failures_to_deliver": (
            "/api/shorts/{ticker}/ftds"
        ),
        "short_interest_float": (
            "/api/shorts/{ticker}/"
            "interest-float"
        ),
        "short_interest_float_v2": (
            "/api/shorts/{ticker}/"
            "interest-float/v2"
        ),
        "short_volumes_by_exchange": (
            "/api/shorts/{ticker}/"
            "volumes-by-exchange"
        ),
    }

    def observation_signal(
        self,
        signal_name,
        ticker=None,
        params=None,
        force_refresh=False,
    ):
        path_template = (
            self.OBSERVATION_ONLY_ENDPOINTS.get(
                signal_name
            )
        )

        if not path_template:
            raise ValueError(
                "UNKNOWN_UNUSUAL_WHALES_"
                f"OBSERVATION_SIGNAL: {signal_name}"
            )

        requires_ticker = (
            "{ticker}" in path_template
        )

        normalized_ticker = (
            str(ticker or "")
            .upper()
            .strip()
        )

        if (
            requires_ticker
            and not normalized_ticker
        ):
            raise ValueError(
                f"ticker is required for {signal_name}"
            )

        path = path_template.format(
            ticker=normalized_ticker
        )

        return self._get(
            path,
            params=params,
            allow_forbidden=True,
            force_refresh=force_refresh,
        )

    def observation_bundle(
        self,
        ticker,
        signal_names=None,
        force_refresh=False,
    ):
        ticker = (
            str(ticker or "")
            .upper()
            .strip()
        )

        selected = (
            list(signal_names)
            if signal_names is not None
            else list(
                self.OBSERVATION_ONLY_ENDPOINTS
            )
        )

        signals = {}
        available = []
        unavailable = []
        degraded = []

        for signal_name in selected:
            try:
                value = self.observation_signal(
                    signal_name,
                    ticker=ticker,
                    force_refresh=force_refresh,
                )

                signals[signal_name] = value

                if value is None:
                    unavailable.append(
                        signal_name
                    )
                else:
                    available.append(
                        signal_name
                    )

            except Exception as exc:
                signals[signal_name] = {
                    "error": repr(exc),
                    "status": (
                        "UNUSUAL_WHALES_SIGNAL_"
                        "COLLECTION_DEGRADED"
                    ),
                }

                degraded.append(
                    signal_name
                )

        return {
            "timestamp": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "provider": "UNUSUAL_WHALES",
            "ticker": ticker,
            "requested_signal_count": len(
                selected
            ),
            "available_signal_count": len(
                available
            ),
            "unavailable_signal_count": len(
                unavailable
            ),
            "degraded_signal_count": len(
                degraded
            ),
            "available_signals": available,
            "unavailable_signals": unavailable,
            "degraded_signals": degraded,
            "signals": signals,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "UNUSUAL_WHALES_OBSERVATION_"
                "BUNDLE_READY"
            ),
        }

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
