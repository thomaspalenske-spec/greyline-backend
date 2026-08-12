"""Long-lived TradeStation quote STREAM that continuously warms the quote cache.

WHY: the 5s fast-quote heartbeat, the universe scanner, and ~30 scoring engines all read quotes through
TradeStationQuoteLiveEngine, which serves any cache entry younger than its 60s TTL. This engine holds ONE
persistent `/v3/marketdata/stream/quotes/{symbols}` connection and writes each streamed quote straight into
that cache — so during market hours those callers hit warm cache instead of polling REST (the batch/poll
machinery only exists to survive the 429s that streaming avoids entirely).

SAFETY (this is a pure cache-WARMER, never a dependency):
  * If the stream is disabled, drops, hangs, or errors, its cache entries simply age past the 60s TTL and
    EVERY caller falls back to the existing REST path. Worst case == today's behavior. Zero regression.
  * Runs in its OWN daemon thread, isolated from the scheduler — a hung stream hangs only itself (the
    scheduler reads the cache, never the socket). A dead connection is caught by the between-bytes read
    timeout and reconnected with capped exponential backoff.
  * Idles (no open socket) while the market is closed, so there's no overnight reconnect churn.
  * Gated OFF by default (GREYLINE_TS_QUOTE_STREAM_ENABLED). Never places orders; read-only market data.
"""

import json
import threading
import time
from datetime import datetime
from os import getenv

import requests

from app.services.env_reload import reload_env
from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class TradeStationQuoteStreamEngine:

    _thread = None
    _stop = threading.Event()
    _lock = threading.Lock()
    _state = {"status": "STOPPED", "connected": False, "symbols": [], "frames": 0,
              "last_frame_at": None, "last_error": None, "reconnects": 0, "started_at": None}

    # The HOT set worth streaming: the sleeve baskets + core index proxies the scoring engines poll most.
    # env GREYLINE_TS_STREAM_SYMBOLS extends it; GREYLINE_TS_STREAM_MAX caps it (TS streaming concurrency +
    # URL length). Held broker positions could be folded in later — kept simple + bounded for the first cut.
    DEFAULT_CORE = ["SPY", "QQQ", "IWM", "SVXY", "QQQM", "GLDM", "EFA", "EEM", "TLT", "IEF",
                    "DBC", "USMV", "SPLV", "EFAV", "XMLV", "SGOV"]

    # ---- config ----------------------------------------------------------------------------------
    @classmethod
    def enabled(cls):
        return (getenv("GREYLINE_TS_QUOTE_STREAM_ENABLED", "") or "").strip().lower() == "true"

    @classmethod
    def _symbols(cls):
        syms = list(cls.DEFAULT_CORE)
        for s in (getenv("GREYLINE_TS_STREAM_SYMBOLS", "") or "").replace(",", " ").split():
            u = s.upper().strip()
            if u and u not in syms:
                syms.append(u)
        try:
            cap = int(getenv("GREYLINE_TS_STREAM_MAX", "40") or 40)
        except ValueError:
            cap = 40
        return syms[:max(1, cap)]

    @staticmethod
    def _market_open():
        try:
            from app.services.market_hours_engine import MarketHoursEngine
            return bool(MarketHoursEngine().status().get("is_regular_session"))
        except Exception:
            return True   # fail-open: if we can't tell, allow the stream (read timeout still bounds it)

    # ---- lifecycle -------------------------------------------------------------------------------
    @classmethod
    def start_if_enabled(cls):
        reload_env()
        if not cls.enabled():
            return {"status": "STREAM_DISABLED"}
        with cls._lock:
            if cls._thread and cls._thread.is_alive():
                return {"status": "STREAM_ALREADY_RUNNING"}
            cls._stop.clear()
            cls._thread = threading.Thread(target=cls._run, name="ts-quote-stream", daemon=True)
            cls._state.update({"status": "STARTING", "started_at": datetime.utcnow().isoformat(),
                               "last_error": None})
            cls._thread.start()
        return {"status": "STREAM_STARTED", "symbols": cls._symbols()}

    @classmethod
    def stop(cls):
        cls._stop.set()
        cls._state.update({"status": "STOPPING", "connected": False})
        return {"status": "STREAM_STOPPING"}

    @classmethod
    def status(cls):
        st = dict(cls._state)
        st["alive"] = bool(cls._thread and cls._thread.is_alive())
        st["enabled"] = cls.enabled()
        laf = st.get("last_frame_at")
        st["stale_seconds"] = round(time.time() - laf, 1) if laf else None
        return st

    # ---- run loop --------------------------------------------------------------------------------
    @classmethod
    def _run(cls):
        backoff = 1.0
        while not cls._stop.is_set():
            if not cls._market_open():
                cls._state.update({"status": "IDLE_MARKET_CLOSED", "connected": False})
                cls._stop.wait(60.0)          # no open socket overnight; re-check each minute
                backoff = 1.0
                continue
            try:
                cls._stream_once()            # returns when the stream ends; raises on error
                backoff = 1.0                 # a clean end resets backoff
            except Exception as e:
                cls._state["last_error"] = repr(e)[:160]
            cls._state["connected"] = False
            if cls._stop.is_set():
                break
            cls._state["reconnects"] += 1
            cls._stop.wait(min(backoff, 30.0))   # capped exponential backoff, interruptible by stop()
            backoff = min(backoff * 2, 30.0)
        cls._state["status"] = "STOPPED"

    @classmethod
    def _stream_once(cls):
        reload_env()
        TradeStationTokenMaintenanceEngine().evaluate()
        token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        syms = cls._symbols()
        if not token or not syms:
            raise RuntimeError("no access token or symbols")
        cls._state["symbols"] = syms
        url = base.rstrip("/") + "/v3/marketdata/stream/quotes/" + ",".join(syms)
        try:
            connect_to = float(getenv("GREYLINE_TS_STREAM_CONNECT_TIMEOUT", "8") or 8)
            read_to = float(getenv("GREYLINE_TS_STREAM_READ_TIMEOUT", "35") or 35)  # > TS heartbeat interval
        except ValueError:
            connect_to, read_to = 8.0, 35.0
        with requests.get(url,
                          headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/vnd.tradestation.streams.v2+json"},
                          stream=True, timeout=(connect_to, read_to)) as resp:
            if resp.status_code != 200:
                raise RuntimeError("stream http %s" % resp.status_code)
            cls._state.update({"status": "CONNECTED", "connected": True, "last_error": None})
            for line in resp.iter_lines():
                if cls._stop.is_set():
                    break
                if not line:
                    continue
                try:
                    cls._ingest(json.loads(line.decode("utf-8")))
                except Exception:
                    continue                  # a malformed frame never kills the stream

    @staticmethod
    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _ingest(cls, row):
        """Fold one stream frame into the shared quote cache. Frame kinds on a TS quote stream: a QUOTE
        (has 'Symbol'), a heartbeat ({'Heartbeat': n}), a status ({'StreamStatus': ...}), or an error
        ({'Error': ...}). Only quotes update the cache; the rest just prove the socket is alive."""
        if not isinstance(row, dict):
            return
        if row.get("Heartbeat") is not None or row.get("StreamStatus") is not None:
            cls._state["last_frame_at"] = time.time()
            return
        if row.get("Error"):
            cls._state["last_error"] = str(row.get("Error"))[:160]
            return
        sym = str(row.get("Symbol") or "").upper().strip()
        if not sym:
            return
        now = time.time()
        # TS quote-stream frames are PARTIAL (deltas) — a frame may carry only the fields that changed, with
        # the rest absent/null. MERGE the frame onto the prior cached quote so last-known Last/Bid/Ask persist
        # instead of being nulled out (which would make the cache WORSE than a REST read).
        prior = TradeStationQuoteLiveEngine._quote_cache.get(sym) or {}
        prior_row = ((prior.get("response_json") or {}).get("Quotes") or [{}])[0] or {}
        merged = dict(prior_row)
        for k, v in row.items():
            if v is not None:
                merged[k] = v
        merged["Symbol"] = sym
        # NEVER let the stream degrade a symbol below REST: require a usable price before caching. A
        # price-less first frame is dropped, so the caller falls back to REST until a real quote arrives.
        if not any((cls._num(merged.get(f)) or 0) > 0 for f in ("Last", "Bid", "Ask")):
            cls._state["last_frame_at"] = now      # socket alive, just no usable price yet
            return
        # SAME shape TradeStationQuoteLiveEngine.get_quotes writes, so get_quote/get_quotes serve it verbatim
        # as a (very fresh) cache hit — no change needed in either read path.
        TradeStationQuoteLiveEngine._quote_cache[sym] = {
            "timestamp": datetime.utcnow().isoformat(), "broker": "TradeStation", "symbol": sym,
            "http_status": 200, "cache_hit": False, "served_from_stream": True,
            "status": "QUOTE_READ_SUCCESS", "response_json": {"Quotes": [merged]}, "_cache_timestamp": now,
        }
        cls._state["frames"] += 1
        cls._state["last_frame_at"] = now
