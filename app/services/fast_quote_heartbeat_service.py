import json
import threading
from datetime import datetime, timezone
from app.services.execution_governor import ExecutionGovernor
from pathlib import Path

from app.services.market_hours_engine import MarketHoursEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class FastQuoteHeartbeatService:
    _state_file = Path("app/data/runtime/fast_quote_heartbeat_state.json")
    _thread = None
    _stop_event = threading.Event()
    _enabled = False

    _symbols = ["AMD", "NVDA"]
    _interval_market_open_seconds = 5
    _interval_market_closed_seconds = 300

    @classmethod
    def _save_state(cls, state):
        cls._state_file.parent.mkdir(parents=True, exist_ok=True)
        cls._state_file.write_text(json.dumps(state, indent=2))

    @classmethod
    def _load_state(cls):
        if not cls._state_file.exists():
            return {}
        try:
            return json.loads(cls._state_file.read_text())
        except Exception:
            return {}

    @classmethod
    def _parse_trade_time(cls, trade_time):
        if not trade_time:
            return None
        try:
            return datetime.fromisoformat(str(trade_time).replace("Z", "+00:00"))
        except Exception:
            return None

    @classmethod
    def _quote_age_seconds(cls, trade_time):
        parsed = cls._parse_trade_time(trade_time)
        if not parsed:
            return None
        now = datetime.now(timezone.utc)
        return round((now - parsed).total_seconds(), 2)

    @classmethod
    def _health_from_age(cls, market_open, max_quote_age_seconds):
        if max_quote_age_seconds is None:
            return "UNKNOWN"

        if not market_open:
            return "MARKET_CLOSED_LAST_QUOTE_MARK"

        if max_quote_age_seconds <= 30:
            return "FRESH"

        if max_quote_age_seconds <= 60:
            return "ACCEPTABLE"

        if max_quote_age_seconds <= 120:
            return "DEGRADED"

        return "STALE_DATA"

    @classmethod
    def start(cls, symbols=None, interval_market_open_seconds=5, interval_market_closed_seconds=300):
        if symbols:
            cls._symbols = [s.upper().strip() for s in symbols if s.strip()]

        cls._interval_market_open_seconds = int(interval_market_open_seconds)
        cls._interval_market_closed_seconds = int(interval_market_closed_seconds)

        if cls._enabled:
            return cls.status()

        cls._enabled = True
        cls._stop_event.clear()

        cls._thread = threading.Thread(target=cls._run_loop, daemon=True)
        cls._thread.start()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "FAST_QUOTE_HEARTBEAT",
            "symbols": cls._symbols,
            "interval_market_open_seconds": cls._interval_market_open_seconds,
            "interval_market_closed_seconds": cls._interval_market_closed_seconds,
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "FAST_QUOTE_HEARTBEAT_STARTED",
        }

    @classmethod
    def stop(cls):
        cls._enabled = False
        cls._stop_event.set()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "FAST_QUOTE_HEARTBEAT",
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "FAST_QUOTE_HEARTBEAT_STOPPED",
        }

    @classmethod
    def status(cls):
        state = cls._load_state()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "FAST_QUOTE_HEARTBEAT",
            "enabled": cls._enabled,
            "thread_alive": bool(cls._thread and cls._thread.is_alive()),
            "symbols": cls._symbols,
            "interval_market_open_seconds": cls._interval_market_open_seconds,
            "interval_market_closed_seconds": cls._interval_market_closed_seconds,
            "state": state,
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "FAST_QUOTE_HEARTBEAT_STATUS_READY",
        }

    @classmethod
    def run_once(cls, symbols=None):
        if symbols:
            cls._symbols = [s.upper().strip() for s in symbols if s.strip()]
        return cls._capture_cycle()

    @classmethod
    def _run_loop(cls):
        while not cls._stop_event.is_set():
            state = cls._capture_cycle()
            market_open = state.get("market_open", False)
            interval = cls._interval_market_open_seconds if market_open else cls._interval_market_closed_seconds
            cls._stop_event.wait(interval)

    @classmethod
    def _extract_quote_row(cls, quote_result):
        response_json = quote_result.get("response_json") or {}
        quotes = response_json.get("Quotes") or []
        return quotes[0] if quotes else {}

    @classmethod
    def _capture_cycle(cls):
        started = datetime.utcnow()
        market = MarketHoursEngine().status()
        market_open = bool(market.get("is_regular_session"))

        quote_engine = TradeStationQuoteLiveEngine()
        symbols = {}
        quote_ages = []

        for symbol in cls._symbols:
            quote_result = quote_engine.get_quote(symbol)
            quote_row = cls._extract_quote_row(quote_result)

            trade_time = quote_row.get("TradeTime")
            age_seconds = cls._quote_age_seconds(trade_time)

            if age_seconds is not None:
                quote_ages.append(age_seconds)

            symbols[symbol] = {
                "symbol": symbol,
                "status": quote_result.get("status"),
                "http_status": quote_result.get("http_status"),
                "last": quote_row.get("Last"),
                "bid": quote_row.get("Bid"),
                "ask": quote_row.get("Ask"),
                "trade_time": trade_time,
                "quote_age_seconds": age_seconds,
                "captured_at": datetime.utcnow().isoformat(),
            }

        finished = datetime.utcnow()
        latency_ms = round((finished - started).total_seconds() * 1000, 2)

        average_quote_age_seconds = round(sum(quote_ages) / len(quote_ages), 2) if quote_ages else None
        max_quote_age_seconds = round(max(quote_ages), 2) if quote_ages else None
        market_data_health = cls._health_from_age(market_open, max_quote_age_seconds)

        state = {
            "timestamp": finished.isoformat(),
            "system": "GreyLine",
            "source": "FAST_QUOTE_HEARTBEAT",
            "market_state": market.get("state"),
            "market_open": market_open,
            "symbol_count": len(cls._symbols),
            "symbols": symbols,
            "average_quote_age_seconds": average_quote_age_seconds,
            "max_quote_age_seconds": max_quote_age_seconds,
            "market_data_health": market_data_health,
            "market_open_health_thresholds": {
                "fresh_seconds": 30,
                "acceptable_seconds": 60,
                "degraded_seconds": 120
            },
            "cycle_latency_ms": latency_ms,
            "execution_enabled": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("execution_enabled"),
            "order_placement_allowed": ExecutionGovernor().evaluate_execution_permission("EXECUTE").get("order_placement_allowed"),
            "status": "FAST_QUOTE_HEARTBEAT_CYCLE_COMPLETE",
        }

        cls._save_state(state)
        return state
