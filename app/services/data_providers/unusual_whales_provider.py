import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import requests
from dotenv import load_dotenv

load_dotenv('.env')
load_dotenv('.env.local', override=True)


class UnusualWhalesProvider:
    BASE_URL = "https://api.unusualwhales.com"

    _cache = {}
    _cache_lock = Lock()
    _usage_lock = Lock()
    _usage_path = Path("app/data/unusual_whales_api_usage.json")

    def __init__(self):
        self.api_key = os.environ["UNUSUAL_WHALES_API_KEY"]
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

        if not force_refresh:
            with self._cache_lock:
                cached = self._cache.get(cache_key)

            if cached and now - cached["timestamp"] < ttl:
                self._record_cache_hit()
                return cached["value"]

        self._consume_budget()

        response = self.session.get(
            self.BASE_URL + path,
            params=params,
            timeout=20,
        )

        if allow_forbidden and response.status_code == 403:
            value = None
        else:
            response.raise_for_status()
            value = response.json()

        provider_daily_count = response.headers.get(
            "x-uw-daily-req-count"
        )
        provider_daily_limit = response.headers.get(
            "x-uw-token-req-limit"
        )

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
                "timestamp": now,
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
