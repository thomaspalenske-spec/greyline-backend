"""Vanna/charm SHADOW forward-test — the 'vanna rally into OPEX', a second-order dealer-flow strategy.

Distinct from the GEX gamma-pinning strategy: this trades the CHARM (delta-decay-over-time) and VANNA
(delta-sensitivity-to-vol) hedging flows. Dealers are typically net SHORT vanna, so when implied vol FALLS
they must BUY the underlying to re-hedge — the well-documented 'vanna rally'. That buy-pressure concentrates
in the days INTO monthly OPEX (3rd Friday), as time decay (charm) forces predictable re-hedging and vol
mean-reverts down. Funds systematically go LONG the index into OPEX to capture it.

Testable signal here: LONG SPY/QQQ during the OPEX window (<= OPEX_WINDOW business days to the 3rd Friday)
when net VANNA is negative (the vanna-rally setup); hold to OPEX, exit at expiry / a stop / a vol-spike.
MEASUREMENT-ONLY: trades the underlying on PAPER, NO orders/budget — same zero-capital discipline as the
other shadows. net_vanna/net_charm from UW greek_exposure; spot from the TradeStation live quote. The sign
thresholds are deliberately simple; the SHADOW measures whether the effect survives forward + net of cost.
"""

import json
import math
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path


def _rigorous_verdict(rets, min_n):
    """Judge this shadow's cost-net returns on the SAME rigorous bar the live edge court uses
    (small-sample-t 95% CI + min-N), so a shadow 'proving' an edge means what a live sleeve does.
    Best-effort — a soft summary still ships if the court import ever fails."""
    try:
        from app.services.edge_persistence_engine import EdgePersistenceEngine
        return EdgePersistenceEngine.verdict_from_returns(rets, min_n=min_n)
    except Exception:
        return None


class VannaCharmShadowEngine:

    NAMES = ["SPY", "QQQ"]           # deepest index options — where dealer vanna/charm flows dominate
    STATE = Path("app/data/vanna_charm")
    OPEN = STATE / "open_positions.json"
    CLOSED = STATE / "closed_trades.jsonl"

    OPEX_WINDOW_DAYS = 8            # enter within this many BUSINESS days of the 3rd-Friday OPEX
    STOP_PCT = 0.025               # 2.5% stop — a vol SPIKE inverts the vanna flow (dealers sell), bail
    COST_ROUNDTRIP = 0.0006        # ~6bps equity round-trip
    MIN_CLOSED = 8
    TRADING_DAYS = 252

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_VANNA_CHARM_SHADOW", "true") or "true").strip().lower() == "true"

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
    def _next_opex(cls):
        """The next monthly OPEX (3rd Friday) strictly after today."""
        today = cls._today()
        for off in (0, 1, 2):
            y = today.year + (today.month - 1 + off) // 12
            mo = (today.month - 1 + off) % 12 + 1
            d = date(y, mo, 1)
            while d.weekday() != 4:          # first Friday
                d += timedelta(days=1)
            third_friday = d + timedelta(days=14)
            if third_friday > today:
                return third_friday
        return None

    @classmethod
    def _biz_days_between(cls, a, b):
        """Business days from date a to date b (a<b), else 0."""
        if not a or not b or b <= a:
            return 0
        n, d = 0, a
        while d < b:
            d += timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return n

    # ---- market reads --------------------------------------------------------------------------

    def _greeks(self, name):
        """{net_vanna, net_charm} (call+put) from UW greek_exposure latest, or {}."""
        try:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            r = UnusualWhalesProvider().greek_exposure(name) or {}
            rows = r.get("data") if isinstance(r.get("data"), list) else (r if isinstance(r, list) else [])
            rows = [x for x in rows if x.get("date")]
            if not rows:
                return {}
            last = max(rows, key=lambda x: str(x.get("date"))[:10])
            cv, pv = self._f(last.get("call_vanna")), self._f(last.get("put_vanna"))
            cc, pc = self._f(last.get("call_charm")), self._f(last.get("put_charm"))
            if cv is None or pv is None:
                return {}
            return {"net_vanna": round(cv + pv, 0), "net_charm": round((cc or 0) + (pc or 0), 0),
                    "date": str(last.get("date"))[:10]}
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

    def signal(self, name, spot=None, greeks=None):
        opex = self._next_opex()
        dte = self._biz_days_between(self._today(), opex)
        g = greeks if greeks is not None else self._greeks(name)
        base = {"name": name, "opex": opex.isoformat() if opex else None, "biz_days_to_opex": dte, **g}
        if spot is None:
            spot = self._spots([name]).get(name)
        base["spot"] = round(spot, 2) if spot else None
        if not g or not spot:
            return {**base, "action": "FLAT", "reason": "no greeks/spot"}
        if not (1 <= dte <= self.OPEX_WINDOW_DAYS):
            return {**base, "action": "FLAT",
                    "reason": f"outside OPEX window (dte {dte}, need 1-{self.OPEX_WINDOW_DAYS})"}
        if g["net_vanna"] < 0:      # dealers short vanna -> falling vol/time-decay into OPEX = buy pressure
            return {**base, "action": "LONG",
                    "reason": "OPEX window + net vanna negative — vanna-rally setup (dealers buy as vol decays)"}
        return {**base, "action": "FLAT", "reason": "OPEX window but net vanna >= 0 (no rally setup)"}

    def signals(self):
        spots = self._spots(self.NAMES)
        return [self.signal(n, spots.get(n)) for n in self.NAMES]

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

    MARK_MARKER = STATE / "last_mark.json"
    MARK_INTERVAL_MIN = 60          # OPEX-horizon — mark hourly, not every scheduler cycle (spares UW/TS)

    def _mark_due(self):
        import time
        try:
            return (time.time() - float(json.loads(self.MARK_MARKER.read_text()).get("at", 0))) >= self.MARK_INTERVAL_MIN * 60
        except Exception:
            return True

    def _stamp_mark(self):
        import time
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            self.MARK_MARKER.write_text(json.dumps({"at": time.time()}))
        except Exception:
            pass

    def mark(self):
        if not self.enabled():
            return {"status": "VANNA_SHADOW_DISABLED", "acted": False}
        if not self._mark_due():
            return {"status": "VANNA_SHADOW_NOT_DUE", "acted": False}
        self._stamp_mark()
        spots = self._spots(self.NAMES)
        if not spots:
            return {"status": "VANNA_SHADOW_NO_SPOT", "acted": False}
        openp = self._load_open()
        closed_now, opened_now = 0, 0

        # 1) manage open longs — exit at OPEX (effect resolves at expiry) or a stop
        for name in list(openp.keys()):
            pos, spot = openp[name], spots.get(name)
            if not spot:
                continue
            entry = self._f(pos["entry"])
            try:
                opex = date.fromisoformat(pos["opex"])
            except (ValueError, TypeError, KeyError):
                opex = None
            ret = spot / entry - 1
            reason = None
            if opex and self._today() >= opex:
                reason = "opex"                                  # held to expiration — the effect's horizon
            elif ret <= -self.STOP_PCT:
                reason = "stop"                                  # vol spike inverted the flow
            if reason:
                net = ret - self.COST_ROUNDTRIP
                self._append_closed({"name": name, "opened": pos["opened"], "opex": pos.get("opex"),
                                     "closed_at": datetime.utcnow().isoformat(), "entry": round(entry, 2),
                                     "exit": round(spot, 2), "exit_reason": reason,
                                     "entry_net_vanna": pos.get("net_vanna"),
                                     "gross_return": round(ret, 6), "net_return": round(net, 6)})
                del openp[name]
                closed_now += 1

        # 2) open new longs on a fresh vanna-rally signal (one per name)
        for name in self.NAMES:
            if name in openp:
                continue
            sig = self.signal(name, spots.get(name))
            if sig.get("action") == "LONG":
                openp[name] = {"entry": sig["spot"], "opened": self._today().isoformat(),
                               "opened_at": datetime.utcnow().isoformat(), "opex": sig.get("opex"),
                               "net_vanna": sig.get("net_vanna"), "net_charm": sig.get("net_charm")}
                opened_now += 1

        self._save_open(openp)
        return {"status": "VANNA_SHADOW_MARKED", "acted": bool(closed_now or opened_now),
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
        rigorous = _rigorous_verdict(rets, self.MIN_CLOSED)   # SAME bar the live court uses
        openp = self._load_open()
        base = {
            "timestamp": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            "engine": "VannaCharmShadowEngine",
            "names": list(self.NAMES),
            "open_positions": [{"name": k, **v} for k, v in openp.items()],
            "signals": self.signals(),
            "closed_trades": n, "min_closed": self.MIN_CLOSED,
            "rigorous_verdict": rigorous,
            "next_opex": (self._next_opex().isoformat() if self._next_opex() else None),
            "params": {"opex_window_days": self.OPEX_WINDOW_DAYS, "stop_pct": self.STOP_PCT,
                       "cost_roundtrip_bps": round(self.COST_ROUNDTRIP * 1e4, 1)},
            "note": ("SHADOW forward-test of the vanna-rally-into-OPEX: LONG the index in the OPEX window when "
                     "net vanna is negative. Trades the underlying, NO orders, NO budget."),
        }
        if n == 0:
            return {**base, "status": "VANNA_SHADOW_NO_DATA",
                    "verdict": "no closed trades yet — opens LONG in the OPEX window on a negative-vanna setup"}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        wins = sum(1 for r in rets if r > 0)
        accumulating = n < self.MIN_CLOSED
        sharpe = round(mean / sd * math.sqrt(12), 2) if sd else 0.0     # ~monthly (one OPEX cycle) trades
        return {
            **base,
            "status": "VANNA_SHADOW_ACCUMULATING" if accumulating else "VANNA_SHADOW_MEASURING",
            "cumulative_return_pct": round(100 * (eq - 1), 2),
            "avg_net_return_bps": round(mean * 1e4, 1),
            "win_rate_pct": round(100 * wins / n, 1),
            "annualized_sharpe": sharpe,
            "verdict": (f"accumulating ({n}/{self.MIN_CLOSED} closed) — not enough to trust yet" if accumulating
                        else f"measuring: {n} closed, win rate {round(100*wins/n,1)}%, avg {round(mean*1e4,1)}bps, "
                             f"Sharpe {sharpe}"),
        }
