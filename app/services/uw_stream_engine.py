"""Unusual Whales WebSocket push feed — a cache-warmer for UW live data (price / GEX), the UW analog of
the TradeStation quote-stream cache-warmer.

WHY: GreyLine polls UW per-symbol over REST for price and dealer-gamma (GEX). A long-lived WS push feed
keeps a fresh in-memory snapshot so those consumers can read a warm value instead of a REST round-trip
(lower API load + lower latency). Like every stream engine here it is a PURE, ADDITIVE cache-warmer:
  * Nothing depends on it. When it's disabled/dropped/stale, callers keep using their existing REST path
    unchanged — worst case == pre-stream behaviour. ZERO regression (verified: it warms its OWN cache and
    exposes it on /uw-stream; no existing read path is rewired here).
  * Own daemon thread running an asyncio loop, ISOLATED from the scheduler. A hung socket hangs only
    itself; reconnect with capped backoff; idles (no open socket) while the market is closed.
  * Gated OFF by default (GREYLINE_UW_STREAM_ENABLED). Read-only market data; never places orders.

PROTOCOL (probed 2026-08-13): wss://api.unusualwhales.com/socket?token=KEY ; join a channel with
{"channel":"<chan>","msg_type":"join"} -> ack ["<chan>",{"response":{},"status":"ok"}] ; data frames
then arrive as ["<chan>", <payload>]. Channels: price:<SYM>, gex:<SYM>, flow-alerts, news, ...

NOTE: the consumer wiring (having the GEX/price REST readers prefer this warm cache) is the follow-up —
this lands the proven WS plumbing + observability, gated OFF, so it can be switched on and wired safely.
"""

import json
import threading
import time
from datetime import datetime
from os import getenv

from app.services.env_reload import reload_env


class UWStreamEngine:

    _thread = None
    _stop = threading.Event()
    _lock = threading.Lock()
    _cache = {}                       # {channel: {"payload": ..., "ts": epoch}}
    _state = {"status": "STOPPED", "connected": False, "channels": [], "frames": 0,
              "last_frame_at": None, "last_error": None, "reconnects": 0, "started_at": None}

    DEFAULT_CHANNELS = ["price:SPY", "price:QQQ", "price:IWM", "gex:SPY"]
    WS_URL = "wss://api.unusualwhales.com/socket"

    # ---- config ----------------------------------------------------------------------------------
    @classmethod
    def enabled(cls):
        return (getenv("GREYLINE_UW_STREAM_ENABLED", "") or "").strip().lower() == "true"

    @classmethod
    def _channels(cls):
        chans = list(cls.DEFAULT_CHANNELS)
        for c in (getenv("GREYLINE_UW_STREAM_CHANNELS", "") or "").replace(",", " ").split():
            c = c.strip()
            if c and c not in chans:
                chans.append(c)
        try:
            cap = int(getenv("GREYLINE_UW_STREAM_MAX", "40") or 40)
        except ValueError:
            cap = 40
        return chans[:max(1, cap)]

    @staticmethod
    def _market_open():
        try:
            from app.services.market_hours_engine import MarketHoursEngine
            return bool(MarketHoursEngine().status().get("is_regular_session"))
        except Exception:
            return True

    # ---- read API (for consumers/observability) --------------------------------------------------
    @classmethod
    def latest(cls, channel, max_age_s=60.0):
        """The freshest streamed payload for a channel, or None if absent/stale — so a consumer that
        prefers the warm value can fall back to REST when it's stale (never trust an aged push)."""
        hit = cls._cache.get(channel)
        if not hit:
            return None
        if max_age_s and (time.time() - hit["ts"]) > max_age_s:
            return None
        return hit["payload"]

    @classmethod
    def status(cls):
        st = dict(cls._state)
        st["alive"] = bool(cls._thread and cls._thread.is_alive())
        st["enabled"] = cls.enabled()
        st["cached_channels"] = sorted(cls._cache.keys())
        laf = st.get("last_frame_at")
        st["stale_seconds"] = round(time.time() - laf, 1) if laf else None
        return st

    # ---- lifecycle -------------------------------------------------------------------------------
    @classmethod
    def start_if_enabled(cls):
        reload_env()
        if not cls.enabled():
            return {"status": "UW_STREAM_DISABLED"}
        with cls._lock:
            if cls._thread and cls._thread.is_alive():
                return {"status": "UW_STREAM_ALREADY_RUNNING"}
            cls._stop.clear()
            cls._thread = threading.Thread(target=cls._run_thread, name="uw-stream", daemon=True)
            cls._state.update({"status": "STARTING", "started_at": datetime.utcnow().isoformat(),
                               "last_error": None})
            cls._thread.start()
        return {"status": "UW_STREAM_STARTED", "channels": cls._channels()}

    @classmethod
    def stop(cls):
        cls._stop.set()
        cls._state.update({"status": "STOPPING", "connected": False})
        return {"status": "UW_STREAM_STOPPING"}

    # ---- run loop (asyncio in the daemon thread) -------------------------------------------------
    @classmethod
    def _run_thread(cls):
        import asyncio
        backoff = 1.0
        while not cls._stop.is_set():
            if not cls._market_open():
                cls._state.update({"status": "IDLE_MARKET_CLOSED", "connected": False})
                cls._stop.wait(60.0)
                backoff = 1.0
                continue
            try:
                asyncio.run(cls._session())
                backoff = 1.0
            except Exception as e:
                cls._state["last_error"] = repr(e)[:160]
            cls._state["connected"] = False
            if cls._stop.is_set():
                break
            cls._state["reconnects"] += 1
            cls._stop.wait(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)
        cls._state["status"] = "STOPPED"

    @classmethod
    async def _session(cls):
        import websockets
        reload_env()
        key = getenv("UNUSUAL_WHALES_API_KEY", "")
        chans = cls._channels()
        if not key or not chans:
            raise RuntimeError("no UW api key or channels")
        cls._state["channels"] = chans
        url = f"{cls.WS_URL}?token={key}"
        async with websockets.connect(url, open_timeout=8, close_timeout=3, ping_interval=20) as ws:
            cls._state.update({"status": "CONNECTED", "connected": True, "last_error": None})
            for ch in chans:
                await ws.send(json.dumps({"channel": ch, "msg_type": "join"}))
            while not cls._stop.is_set():
                try:
                    import asyncio
                    raw = await asyncio.wait_for(ws.recv(), timeout=35)
                except Exception:
                    break                       # timeout/closed -> let the outer loop reconnect
                cls._ingest(raw)

    @classmethod
    def _ingest(cls, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        # data + join-ack frames are ["<channel>", <payload>]; errors are {"error": ...}
        if isinstance(msg, list) and len(msg) == 2 and isinstance(msg[0], str):
            channel, payload = msg[0], msg[1]
            # skip the join ack ({"status":"ok"}) — only cache real data payloads
            if isinstance(payload, dict) and payload.get("status") == "ok" and "response" in payload:
                return
            cls._cache[channel] = {"payload": payload, "ts": time.time()}
            cls._state["frames"] += 1
            cls._state["last_frame_at"] = time.time()
        elif isinstance(msg, dict) and msg.get("error"):
            cls._state["last_error"] = str(msg.get("error"))[:160]
