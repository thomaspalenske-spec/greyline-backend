"""TradeStation brokerage POSITIONS stream — a cache-warmer for TradeStationPositionsLiveEngine._CACHE,
the same shape as the quote-stream cache-warmer but for the money-path positions read.

Why this is safe (positions are risk-critical SETS, unlike per-symbol quotes):
  * The stream NEVER trusts itself. It maintains a mirror of the book (TS sends full position objects,
    not partial deltas — see the probed frame schema) and warms the shared cache ONLY while a
    cache-BYPASSING REST cross-check agrees with the mirror. Any mismatch, gap, reconnect, or missed
    delete -> DESYNCED -> it stops warming and the last entry simply ages past the 15s cache TTL, so
    every caller falls back to the exact REST read used today (ZERO regression).
  * Risk direction is favorable: a stale/phantom (already-closed) position OVER-counts exposure ->
    more conservative for the deployment cap, never less. The dangerous direction (missing a real
    position) needs a dropped add-frame, which the periodic cross-check catches within CROSSCHECK_S.
  * Runs in its OWN daemon thread (a hung stream hangs only itself; read timeout bounds it) and NEVER
    places orders — read-only brokerage data.
  * Gated OFF by default (GREYLINE_TS_BROKER_STREAM_ENABLED). Measurement-first: even enabled, its whole
    value is gated behind live cross-check AGREEMENT, which /ts-broker-stream surfaces for a verdict.

Value (honest): the 15s positions cache already collapses the 429 read-storm to ~1 call, so this does
NOT fix rate-limiting — it makes positions sub-second fresh and moves the broker read off the scheduler
cycle's critical path while cross-check agreement holds.
"""

import json
import threading
import time
from datetime import datetime
from os import getenv

import requests

from app.services.env_reload import reload_env
from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine


class TradeStationBrokerStreamEngine:

    _thread = None
    _stop = threading.Event()
    _lock = threading.Lock()
    _mirror = {}                      # PositionID -> position object (the streamed book)
    _account = None
    _src = None                       # resolved account source (mode/host_kind) for the warmed result shape
    _synced = False                   # mirror currently agrees with a fresh REST cross-check
    _snapshot_complete = False
    _last_crosscheck = None           # {ok, mismatch, ts_iso, mirror_n, rest_n}
    _last_crosscheck_mono = 0.0
    _state = {"status": "STOPPED", "connected": False, "frames": 0, "last_frame_at": None,
              "last_error": None, "reconnects": 0, "started_at": None, "warm_writes": 0}

    CROSSCHECK_S_DEFAULT = 45.0       # re-verify the mirror vs REST at least this often

    # ---- config ----------------------------------------------------------------------------------
    @classmethod
    def enabled(cls):
        return (getenv("GREYLINE_TS_BROKER_STREAM_ENABLED", "") or "").strip().lower() == "true"

    @classmethod
    def _crosscheck_s(cls):
        try:
            v = getenv("GREYLINE_TS_BROKER_STREAM_CROSSCHECK_S", "")
            return float(v) if str(v).strip() else cls.CROSSCHECK_S_DEFAULT
        except (TypeError, ValueError):
            return cls.CROSSCHECK_S_DEFAULT

    @staticmethod
    def _market_open():
        try:
            from app.services.market_hours_engine import MarketHoursEngine
            return bool(MarketHoursEngine().status().get("is_regular_session"))
        except Exception:
            return True   # fail-open: read timeout still bounds a hung socket

    # ---- frame parsing ---------------------------------------------------------------------------
    @staticmethod
    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _signed_qty(cls, obj):
        """Signed share count: Short -> negative. Matches how REST positions are interpreted downstream."""
        q = cls._num(obj.get("Quantity"))
        if q is None:
            return None
        return -abs(q) if str(obj.get("LongShort", "")).lower().startswith("short") else abs(q)

    @classmethod
    def _mirror_by_symbol(cls):
        agg = {}
        for obj in cls._mirror.values():
            s = obj.get("Symbol")
            q = cls._signed_qty(obj)
            if s and q is not None:
                agg[s] = agg.get(s, 0.0) + q
        return {s: q for s, q in agg.items() if abs(q) > 1e-9}

    @classmethod
    def _rest_by_symbol(cls):
        """Ground-truth: a cache-BYPASSING REST positions read parsed to {symbol: signed_qty}."""
        res = TradeStationPositionsLiveEngine().get_positions(bypass_cache=True)
        if res.get("status") != "POSITIONS_READ_SUCCESS":
            return None
        rows = ((res.get("response_json") or {}).get("Positions")) or []
        agg = {}
        for obj in rows:
            s = obj.get("Symbol")
            q = cls._signed_qty(obj)
            if s and q is not None:
                agg[s] = agg.get(s, 0.0) + q
        return {s: q for s, q in agg.items() if abs(q) > 1e-9}

    @classmethod
    def _crosscheck(cls):
        """Compare the streamed mirror against REST ground truth. Sets _synced; never raises."""
        try:
            rest = cls._rest_by_symbol()
        except Exception as e:
            cls._state["last_error"] = ("crosscheck: %r" % e)[:160]
            rest = None
        if rest is None:                                  # can't verify -> refuse to warm
            cls._synced = False
            cls._last_crosscheck = {"ok": False, "reason": "REST_UNAVAILABLE",
                                    "ts_iso": datetime.utcnow().isoformat()}
            cls._last_crosscheck_mono = time.monotonic()
            return
        mine = cls._mirror_by_symbol()
        syms = set(mine) | set(rest)
        mismatch = {s: {"stream": mine.get(s, 0.0), "rest": rest.get(s, 0.0)}
                    for s in syms if abs(mine.get(s, 0.0) - rest.get(s, 0.0)) > 1e-6}
        cls._synced = not mismatch
        cls._last_crosscheck = {"ok": cls._synced, "mismatch": mismatch,
                                "mirror_n": len(mine), "rest_n": len(rest),
                                "ts_iso": datetime.utcnow().isoformat()}
        cls._last_crosscheck_mono = time.monotonic()

    @classmethod
    def _warm(cls):
        """Write the streamed book into the shared positions cache — ONLY when synced. Shapes the result
        exactly like a successful REST get_positions() so every downstream parser is unaffected."""
        if not (cls._synced and cls._account and cls._src):
            return
        positions = list(cls._mirror.values())
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "broker": "TradeStation",
            "positions_attempted": True,
            "http_status": 200,
            "execution_enabled": False,
            "account_mode": cls._src.get("mode"),
            "account_id": cls._account,
            "host_kind": cls._src.get("host_kind"),
            "status": "POSITIONS_READ_SUCCESS",
            "response_preview": "",
            "response_json": {"Positions": positions},
            "served_from_cache": False,
            "served_from_stream": True,
        }
        TradeStationPositionsLiveEngine._CACHE[cls._account] = (time.monotonic(), result)
        cls._state["warm_writes"] += 1

    # ---- lifecycle -------------------------------------------------------------------------------
    @classmethod
    def start_if_enabled(cls):
        reload_env()
        if not cls.enabled():
            return {"status": "BROKER_STREAM_DISABLED"}
        with cls._lock:
            if cls._thread and cls._thread.is_alive():
                return {"status": "BROKER_STREAM_ALREADY_RUNNING"}
            cls._stop.clear()
            cls._thread = threading.Thread(target=cls._run, name="ts-broker-stream", daemon=True)
            cls._state.update({"status": "STARTING", "started_at": datetime.utcnow().isoformat(),
                               "last_error": None})
            cls._thread.start()
        return {"status": "BROKER_STREAM_STARTED"}

    @classmethod
    def stop(cls):
        cls._stop.set()
        cls._state.update({"status": "STOPPING", "connected": False})
        cls._synced = False
        return {"status": "BROKER_STREAM_STOPPING"}

    @classmethod
    def status(cls):
        st = dict(cls._state)
        st["alive"] = bool(cls._thread and cls._thread.is_alive())
        st["enabled"] = cls.enabled()
        st["synced"] = cls._synced
        st["snapshot_complete"] = cls._snapshot_complete
        st["mirror_positions"] = len(cls._mirror)
        st["last_crosscheck"] = cls._last_crosscheck
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
                cls._synced = False
                cls._stop.wait(60.0)
                backoff = 1.0
                continue
            try:
                cls._stream_once()
                backoff = 1.0
            except Exception as e:
                cls._state["last_error"] = repr(e)[:160]
            cls._state["connected"] = False
            cls._synced = False                       # a dropped stream must never keep warming
            if cls._stop.is_set():
                break
            cls._state["reconnects"] += 1
            cls._stop.wait(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)
        cls._state["status"] = "STOPPED"

    @classmethod
    def _stream_once(cls):
        reload_env()
        TradeStationTokenMaintenanceEngine().evaluate()
        token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        from app.services.tradestation_account_source_engine import TradeStationAccountSourceEngine
        src = TradeStationAccountSourceEngine().resolve()
        account = src.get("account_id")
        base = src.get("base_url") or getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        if not token or not account or not src.get("ok"):
            raise RuntimeError("no access token / account")
        cls._account, cls._src = account, src
        # fresh connect => rebuild the book from scratch; refuse to warm until re-verified
        cls._mirror = {}
        cls._snapshot_complete = False
        cls._synced = False
        url = base.rstrip("/") + "/v3/brokerage/stream/accounts/%s/positions" % account
        try:
            connect_to = float(getenv("GREYLINE_TS_STREAM_CONNECT_TIMEOUT", "8") or 8)
            read_to = float(getenv("GREYLINE_TS_STREAM_READ_TIMEOUT", "35") or 35)
        except ValueError:
            connect_to, read_to = 8.0, 35.0
        with requests.get(url,
                          headers={"Authorization": "Bearer %s" % token,
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
                    continue                          # a malformed frame never kills the stream

    @classmethod
    def _ingest(cls, obj):
        if not isinstance(obj, dict):
            return
        cls._state["frames"] += 1
        cls._state["last_frame_at"] = time.time()

        # control frames: Heartbeat / StreamStatus mark the end of the initial snapshot and pace re-checks
        if "Heartbeat" in obj or "StreamStatus" in obj:
            if not cls._snapshot_complete:
                cls._snapshot_complete = True
                cls._crosscheck()                     # first verify right after the snapshot lands
            elif not cls._synced:
                cls._crosscheck()                     # desynced (book changed / prior mismatch): re-verify ASAP
            elif time.monotonic() - cls._last_crosscheck_mono >= cls._crosscheck_s():
                cls._crosscheck()                     # synced: periodic re-verification only
            cls._warm()
            return
        if "Error" in obj or "StreamError" in obj:
            cls._synced = False
            cls._state["last_error"] = str(obj)[:160]
            return

        # position frame — TS sends the FULL position object (probed schema)
        pid = obj.get("PositionID")
        if not pid or not obj.get("Symbol"):
            return
        deleted = str(obj.get("Deleted", "")).lower() in ("true", "1")
        q = cls._signed_qty(obj)
        if deleted or q == 0:
            cls._mirror.pop(pid, None)
        else:
            cls._mirror[pid] = obj
        # after the snapshot, a book change invalidates the last agreement until re-verified on the next
        # heartbeat — so we never warm a post-change book that REST hasn't confirmed yet.
        if cls._snapshot_complete:
            cls._synced = False
