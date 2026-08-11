"""GEX mean-reversion SHADOW forward-test — a genuinely NEW strategy (not the condor filter).

Thesis (dealer-gamma pinning): when market-makers are NET LONG gamma (spot ABOVE UW's gamma_flip) they
trade AGAINST price moves — sell rallies, buy dips — which SUPPRESSES vol and PINS price toward the
gamma_magnet (the max-gamma strike), bounded by the call_wall (resistance) and put_wall (support). So in a
long-gamma regime you FADE the extremes: LONG near/under the put_wall, SHORT near/over the call_wall, both
targeting the magnet. In a SHORT-gamma regime (spot below the flip) dealers AMPLIFY moves — no pin — so the
strategy stands aside (flat) rather than fading a runaway.

MEASUREMENT-ONLY: this trades the UNDERLYING (index ETFs), NO orders, NO budget. It records the signal,
opens a hypothetical position at the live spot, marks it daily, and closes at the magnet (win) / a stop
beyond the wall (loss) / a regime flip / a max hold — booking realized P&L net of a small equity cost. Same
zero-capital forward-test discipline as the other shadows; earns the right to arm on evidence. Gated by
GREYLINE_GEX_STRATEGY_SHADOW. Signal from UW gex_levels; spot from the TradeStation live quote (60s cache).
"""

import json
import math
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path


class GexMeanReversionShadowEngine:

    NAMES = ["SPY", "QQQ", "DIA", "IWM"]   # deepest-gamma index ETFs — where dealer positioning dominates
    #   price. IWM's UW gamma_flip is intermittently null -> it fail-safes to FLAT those days (regime unknown).
    STATE = Path("app/data/gex_strategy")
    OPEN = STATE / "open_positions.json"
    CLOSED = STATE / "closed_trades.jsonl"

    WALL_BUFFER = 0.003              # trigger entry within 0.3% of a wall (catch the fade slightly early)
    STOP_BUFFER = 0.010             # stop 1% BEYOND the wall (thesis broken if price breaks the wall)
    MAX_HOLD_DAYS = 5               # pins usually resolve within a week
    COST_ROUNDTRIP = 0.0006         # ~6bps equity round-trip (spread+fees), netted from each trade
    MIN_CLOSED = 10                 # closed trades before the verdict is trustworthy
    TRADING_DAYS = 252

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_GEX_STRATEGY_SHADOW", "true") or "true").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _today():
        return datetime.utcnow().date()

    @classmethod
    def _biz_days(cls, start_iso):
        try:
            start = date.fromisoformat(str(start_iso)[:10])
        except (ValueError, TypeError):
            return 0
        n, d = 0, start
        today = cls._today()
        while d < today:
            d += timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return n

    # ---- market reads --------------------------------------------------------------------------

    def _gex_levels(self, name):
        """{call_wall, gamma_flip, gamma_magnet, put_wall} floats from UW, or {} on miss."""
        try:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            r = UnusualWhalesProvider().gex_levels(name) or {}
            d = r.get("data") if isinstance(r.get("data"), dict) else r
            out = {k: self._f((d or {}).get(k)) for k in ("call_wall", "gamma_flip", "gamma_magnet", "put_wall")}
            return out if all(out.get(k) for k in ("gamma_flip", "gamma_magnet")) else {}
        except Exception:
            return {}

    def _spots(self, names):
        out = {}
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            q = TradeStationQuoteLiveEngine().get_quotes(sorted(names)) or {}
            for s in names:
                row = (((q.get(s) or {}).get("response_json") or {}).get("Quotes") or [{}])[0]
                px = self._f(row.get("Last")) or self._f(row.get("Close"))
                if px and px > 0:
                    out[s] = px
        except Exception:
            pass
        return out

    # ---- signal --------------------------------------------------------------------------------

    def signal(self, name, spot=None, gex=None):
        """The current fade signal for one name. FLAT unless we're in a long-gamma regime AND price is at a
        wall with the magnet on the reversion side."""
        gex = gex if gex is not None else self._gex_levels(name)
        if not gex:
            return {"name": name, "action": "FLAT", "reason": "no GEX read"}
        if spot is None:
            spot = self._spots([name]).get(name)
        if not spot:
            return {"name": name, "action": "FLAT", "reason": "no spot", **gex}
        flip, magnet = gex["gamma_flip"], gex["gamma_magnet"]
        call_wall, put_wall = gex.get("call_wall"), gex.get("put_wall")
        base = {"name": name, "spot": round(spot, 2), **gex}
        if spot <= flip:
            return {**base, "action": "FLAT", "regime": "short_gamma",
                    "reason": "short-gamma regime (dealers amplify moves — no pin, stand aside)"}
        # LONG-gamma regime -> fade the walls toward the magnet
        if call_wall and spot >= call_wall * (1 - self.WALL_BUFFER) and magnet < spot:
            return {**base, "action": "SHORT", "regime": "long_gamma", "target": round(magnet, 2),
                    "stop": round(call_wall * (1 + self.STOP_BUFFER), 2),
                    "reason": "at/over the call_wall in a long-gamma pin — fade down to the magnet"}
        if put_wall and spot <= put_wall * (1 + self.WALL_BUFFER) and magnet > spot:
            return {**base, "action": "LONG", "regime": "long_gamma", "target": round(magnet, 2),
                    "stop": round(put_wall * (1 - self.STOP_BUFFER), 2),
                    "reason": "at/under the put_wall in a long-gamma pin — fade up to the magnet"}
        return {**base, "action": "FLAT", "regime": "long_gamma",
                "reason": "long-gamma but price is between the walls — no edge, wait for an extreme"}

    _signals_cache = {"at": 0.0, "data": None}
    SIGNALS_TTL = 300               # cache the live signals ~5min so the 15s dashboard can't over-poll UW

    def signals(self):
        import time
        now = time.time()
        c = type(self)._signals_cache
        if c.get("data") is not None and (now - c.get("at", 0)) < self.SIGNALS_TTL:
            return c["data"]
        spots = self._spots(self.NAMES)
        data = [self.signal(n, spots.get(n)) for n in self.NAMES]
        type(self)._signals_cache = {"at": now, "data": data}
        return data

    # ---- state ---------------------------------------------------------------------------------

    def _load_open(self):
        try:
            return json.loads(self.OPEN.read_text())
        except Exception:
            return {}

    def _save_open(self, d):
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            self.OPEN.write_text(json.dumps(d))
        except Exception:
            pass

    def _append_closed(self, rec):
        self.STATE.mkdir(parents=True, exist_ok=True)
        with open(self.CLOSED, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def _closed(self):
        out = []
        try:
            for ln in self.CLOSED.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    # ---- forward-test step ---------------------------------------------------------------------

    def mark(self):
        """Advance the shadow: mark/close open fades, then open new ones on a fresh signal. NO orders."""
        if not self.enabled():
            return {"status": "GEX_SHADOW_DISABLED", "acted": False}
        spots = self._spots(self.NAMES)
        if not spots:
            return {"status": "GEX_SHADOW_NO_SPOT", "acted": False}
        openp = self._load_open()
        closed_now, opened_now = 0, 0

        # 1) manage open fades
        for name in list(openp.keys()):
            pos = openp[name]
            spot = spots.get(name)
            if not spot:
                continue
            gex = self._gex_levels(name)
            entry, side = self._f(pos["entry"]), pos["side"]
            held = self._biz_days(pos["opened"])
            ret = (spot / entry - 1) if side == "LONG" else (entry / spot - 1)
            exit_reason = None
            magnet = gex.get("gamma_magnet")
            flip = gex.get("gamma_flip")
            if gex and flip and ((side == "LONG" and spot <= flip) or (side == "SHORT" and spot <= flip)):
                # regime flipped to short-gamma -> pin thesis gone
                if spot <= flip:
                    exit_reason = "regime_flip"
            if not exit_reason and magnet:
                if side == "LONG" and spot >= magnet:
                    exit_reason = "target"
                elif side == "SHORT" and spot <= magnet:
                    exit_reason = "target"
            if not exit_reason:
                if side == "LONG" and spot <= self._f(pos["stop"]):
                    exit_reason = "stop"
                elif side == "SHORT" and spot >= self._f(pos["stop"]):
                    exit_reason = "stop"
            if not exit_reason and held >= self.MAX_HOLD_DAYS:
                exit_reason = "time"
            if exit_reason:
                net = ret - self.COST_ROUNDTRIP
                self._append_closed({"name": name, "side": side, "opened": pos["opened"],
                                     "closed_at": datetime.utcnow().isoformat(), "entry": round(entry, 2),
                                     "exit": round(spot, 2), "days_held": held, "exit_reason": exit_reason,
                                     "gross_return": round(ret, 6), "net_return": round(net, 6)})
                del openp[name]
                closed_now += 1

        # 2) open new fades on a fresh signal (one position per name)
        for name in self.NAMES:
            if name in openp:
                continue
            sig = self.signal(name, spots.get(name))
            if sig.get("action") in ("LONG", "SHORT"):
                openp[name] = {"side": sig["action"], "entry": sig["spot"], "opened": self._today().isoformat(),
                               "opened_at": datetime.utcnow().isoformat(), "target": sig["target"],
                               "stop": sig["stop"], "entry_gex": {k: sig.get(k) for k in
                               ("call_wall", "gamma_flip", "gamma_magnet", "put_wall")}}
                opened_now += 1

        self._save_open(openp)
        return {"status": "GEX_SHADOW_MARKED", "acted": bool(closed_now or opened_now),
                "closed": closed_now, "opened": opened_now, "open_positions": len(openp)}

    # ---- report --------------------------------------------------------------------------------

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    def report(self):
        closed = self._closed()
        rets = [c["net_return"] for c in closed if c.get("net_return") is not None]
        n = len(rets)
        openp = self._load_open()
        base = {
            "timestamp": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            "engine": "GexMeanReversionShadowEngine",
            "names": list(self.NAMES),
            "open_positions": [{"name": k, **v} for k, v in openp.items()],
            "signals": self.signals(),        # cached live per-name signal (drives the dashboard card)
            "closed_trades": n, "min_closed": self.MIN_CLOSED,
            "params": {"wall_buffer": self.WALL_BUFFER, "stop_buffer": self.STOP_BUFFER,
                       "max_hold_days": self.MAX_HOLD_DAYS, "cost_roundtrip_bps": round(self.COST_ROUNDTRIP * 1e4, 1)},
            "note": ("SHADOW forward-test of GEX mean-reversion — fade the walls toward the gamma-magnet in "
                     "long-gamma pinning regimes. Trades the UNDERLYING, NO orders, NO budget."),
        }
        if n == 0:
            return {**base, "status": "GEX_SHADOW_NO_DATA",
                    "verdict": "no closed fades yet — opens when a name is at a wall in a long-gamma regime"}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        wins = sum(1 for r in rets if r > 0)
        # trades are ~a few days; annualize by an approximate turnover of 252/avg-hold
        avg_hold = max(1.0, sum(c.get("days_held", self.MAX_HOLD_DAYS) for c in closed) / n)
        sharpe = round(mean / sd * math.sqrt(self.TRADING_DAYS / avg_hold), 2) if sd else 0.0
        from collections import Counter
        reasons = Counter(c.get("exit_reason") for c in closed)
        accumulating = n < self.MIN_CLOSED
        return {
            **base,
            "status": "GEX_SHADOW_ACCUMULATING" if accumulating else "GEX_SHADOW_MEASURING",
            "cumulative_return_pct": round(100 * (eq - 1), 2),
            "avg_net_return_bps": round(mean * 1e4, 1),
            "win_rate_pct": round(100 * wins / n, 1),
            "annualized_sharpe": sharpe,
            "exit_reasons": dict(reasons),
            "verdict": (f"accumulating ({n}/{self.MIN_CLOSED} closed) — not enough to trust yet" if accumulating
                        else f"measuring: {n} closed, win rate {round(100*wins/n,1)}%, avg {round(mean*1e4,1)}bps, "
                             f"Sharpe {sharpe}; exits {dict(reasons)}"),
        }
