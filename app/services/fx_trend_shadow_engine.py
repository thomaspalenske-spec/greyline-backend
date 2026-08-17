"""FX trend SHADOW — the third alt-asset measurement, ZERO capital.

Completes the measurement trio (vol ETPs / futures / FX). Time-series trend on the 6 spot-FX pairs: long each
pair with a positive 3-month trailing return, short each negative, equal-weight, rebalanced weekly. FX trends
faster than the managed-futures complex, hence the shorter lookback + weekly cadence (vs the futures shadow's
12-month / monthly). Settled at LIVE pair quotes, net of cost, judged on the live edge court's bar.

NOTE (USD concentration): EURUSD/GBPUSD/AUDUSD are "vs USD" and USDJPY/USDCAD/USDCHF are "USD vs", so an
equal-weight book across all 6 can become a concentrated USD trend bet — that's the honest structure of a
simple FX-trend rule, surfaced here rather than hidden. NO orders, NO budget.
"""

import json
import math
from datetime import datetime, date, timedelta
from os import getenv
from pathlib import Path
from app.services.ttl_cache import ttl_cached


def _rigorous_verdict(rets, min_n):
    try:
        from app.services.edge_persistence_engine import EdgePersistenceEngine
        return EdgePersistenceEngine.verdict_from_returns(rets, min_n=min_n)
    except Exception:
        return None


class FxTrendShadowEngine:

    STATE = Path("app/data/fx_trend_shadow")
    OPEN = STATE / "open_cohort.json"
    CLOSED = STATE / "closed_cohorts.jsonl"

    LOOKBACK = 63                # 3-month FX trend signal
    HOLD_DAYS = 5               # weekly non-overlapping hold
    MIN_COHORTS = 8
    PERIODS_PER_YEAR = 252 / 5

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_FX_TREND_SHADOW", "true") or "true").strip().lower() == "true"

    @staticmethod
    def _cost_roundtrip():
        try:
            return float(getenv("GREYLINE_COST_BPS_ROUND_TRIP", "10")) / 10000.0
        except (TypeError, ValueError):
            return 10 / 10000.0

    @staticmethod
    def _f2(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _today():
        return datetime.utcnow().date()

    @classmethod
    def _biz_days_elapsed(cls, start_iso):
        try:
            start = date.fromisoformat(str(start_iso)[:10])
        except (ValueError, TypeError):
            return 0
        today = cls._today()
        if today <= start:
            return 0
        n, d = 0, start
        while d < today:
            d = d + timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return n

    # ---- universe + trend signal ---------------------------------------------------------------
    def _instruments(self):
        try:
            from app.services.alt_asset_universe_engine import AltAssetUniverseEngine
            return [(i["key"], i["ts_symbol"]) for i in AltAssetUniverseEngine.all()
                    if i["asset_class"] == "fx" and AltAssetUniverseEngine.bar_path(i["key"]).exists()]
        except Exception:
            return []

    def _trailing_return(self, key):
        try:
            import csv
            from app.services.alt_asset_universe_engine import AltAssetUniverseEngine
            closes = [self._f2(r.get("close")) for r in csv.DictReader(open(AltAssetUniverseEngine.bar_path(key)))]
            closes = [c for c in closes if c and c > 0]
        except Exception:
            return None
        if len(closes) < self.LOOKBACK + 1:
            return None
        past = closes[-1 - self.LOOKBACK]
        return (closes[-1] / past - 1.0) if past > 0 else None

    def _signal(self):
        legs = []
        for key, ts_sym in self._instruments():
            tr = self._trailing_return(key)
            if tr is None:
                continue
            legs.append({"symbol": key, "ts_symbol": ts_sym, "side": "BUY" if tr > 0 else "SELL",
                         "trailing_return": round(tr, 6)})
        return legs

    def _live_prices(self, ts_syms):
        out = {}
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            q = TradeStationQuoteLiveEngine()
        except Exception:
            return out
        for ts in sorted(set(ts_syms)):
            try:
                r = q.get_quote(ts) or {}
                row = (((r.get("response_json") or {}).get("Quotes") or [{}]) or [{}])[0]
                px = self._f2(row.get("Last")) or self._f2(row.get("Close"))
                if px and px > 0:
                    out[ts] = px
            except Exception:
                continue
        return out

    # ---- state ---------------------------------------------------------------------------------
    def _load_open(self):
        try:
            return json.loads(self.OPEN.read_text())
        except Exception:
            return []

    def _save_open(self, cohorts):
        try:
            self.STATE.mkdir(parents=True, exist_ok=True)
            self.OPEN.write_text(json.dumps(cohorts))
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

    # ---- mark ----------------------------------------------------------------------------------
    def mark(self):
        if not self.enabled():
            return {"status": "FX_TREND_SHADOW_DISABLED", "acted": False}
        cost = self._cost_roundtrip()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        for co in cohorts:
            legs = co.get("legs", [])
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            prices = self._live_prices([l["ts_symbol"] for l in legs])
            settled = []
            for leg in legs:
                px = prices.get(leg["ts_symbol"])
                ec = self._f2(leg.get("entry_close"))
                if px and ec and ec > 0:
                    g = (px / ec - 1.0) if leg["side"] == "BUY" else (ec / px - 1.0)
                    settled.append({**leg, "exit_close": round(px, 6), "gross_return": round(g, 6)})
            if len(settled) < max(3, int(0.6 * len(legs))):
                still_open.append(co)
                continue
            gross_mean = sum(l["gross_return"] for l in settled) / len(settled)
            rec = {"opened": co.get("opened"), "settled_at": datetime.utcnow().isoformat(),
                   "n_legs": len(settled), "n_long": sum(1 for l in settled if l["side"] == "BUY"),
                   "cost_roundtrip_bps": round(cost * 10000, 2),
                   "gross_return": round(gross_mean, 6), "net_return": round(gross_mean - cost, 6),
                   "legs": [{"symbol": l["symbol"], "side": l["side"], "gross_return": l["gross_return"]} for l in settled]}
            self._append_closed(rec)
            closed_now.append(rec)

        opened = None
        if not still_open:
            picks = self._signal()
            live = self._live_prices([p["ts_symbol"] for p in picks])
            legs = [{**p, "entry_close": round(live[p["ts_symbol"]], 6)} for p in picks if live.get(p["ts_symbol"])]
            if len(legs) >= 4:
                opened = {"opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                          "n_legs": len(legs), "n_long": sum(1 for l in legs if l["side"] == "BUY"), "legs": legs}
                still_open.append(opened)

        self._save_open(still_open)
        return {"status": "FX_TREND_SHADOW_MARKED", "acted": bool(closed_now or opened),
                "cohorts_closed": len(closed_now), "cohort_opened": bool(opened),
                "open_cohorts": len(still_open)}

    # ---- positions + report --------------------------------------------------------------------
    def open_positions(self):
        cohorts = self._load_open()
        prices = self._live_prices([l["ts_symbol"] for co in cohorts for l in co.get("legs", [])])
        rows = []
        for co in cohorts:
            held = self._biz_days_elapsed(co.get("opened"))
            for leg in co.get("legs", []):
                ec = self._f2(leg.get("entry_close")) or 0.0
                cur = prices.get(leg["ts_symbol"])
                unreal = None
                if cur and ec > 0:
                    unreal = (cur / ec - 1.0) if leg["side"] == "BUY" else (ec / cur - 1.0)
                pct = round(100 * unreal, 3) if unreal is not None else None
                rows.append({"symbol": leg["symbol"], "side": leg["side"], "entry_date": co.get("opened"),
                             "entry_close": round(ec, 6) if ec else None,
                             "live_last": round(cur, 6) if cur else None, "unrealized_pct": pct,
                             "trailing_return_pct": round(100 * self._f2(leg.get("trailing_return") or 0), 2),
                             "days_held": held, "days_to_settle": max(0, self.HOLD_DAYS - held)})
        rows.sort(key=lambda r: (r.get("trailing_return_pct") or 0), reverse=True)
        return rows

    @staticmethod
    def _stdev(xs):
        n = len(xs)
        if n < 2:
            return 0.0
        m = sum(xs) / n
        return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def report(self):
        closed = self._closed()
        rets = [c["net_return"] for c in closed if c.get("net_return") is not None]
        n = len(rets)
        positions = self.open_positions()
        base = {"timestamp": datetime.utcnow().isoformat(), "shadow_enabled": self.enabled(),
                "engine": "FxTrendShadowEngine", "universe_size": len(self._instruments()),
                "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS,
                "rigorous_verdict": _rigorous_verdict(rets, self.MIN_COHORTS),
                "open_cohorts": len(self._load_open()), "open_positions": positions,
                "signal": f"FX trend · {self.LOOKBACK}d trailing sign · long/short equal-weight · weekly",
                "hold_days": self.HOLD_DAYS, "cost_roundtrip_bps": round(self._cost_roundtrip() * 10000, 2),
                "note": ("ZERO-capital FX-trend forward-test on the 6 spot pairs. Long/short by 3-month trend, "
                         "weekly, judged on the court's bar. Watch USD concentration (vs-USD vs USD-vs pairs). "
                         "NO orders/budget.")}
        if n == 0:
            return {**base, "status": "FX_TREND_SHADOW_NO_DATA",
                    "verdict": (f"{len(positions)} open ({sum(1 for p in positions if p['side']=='BUY')} long / "
                                f"{sum(1 for p in positions if p['side']=='SELL')} short) — first weekly cohort "
                                f"settles ~{self.HOLD_DAYS} biz days after opening" if positions else
                                "no cohorts yet — the first opens next mark across the FX-trend book")}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        sharpe = round(mean / sd * math.sqrt(self.PERIODS_PER_YEAR), 2) if sd else 0.0
        wins = sum(1 for r in rets if r > 0)
        accumulating = n < self.MIN_COHORTS
        return {**base,
                "status": "FX_TREND_SHADOW_ACCUMULATING" if accumulating else "FX_TREND_SHADOW_MEASURING",
                "cumulative_return_pct": round(100 * (eq - 1), 3),
                "avg_net_return_per_week_bps": round(mean * 10000, 2),
                "annualized_sharpe": sharpe, "win_rate_pct": round(100 * wins / n, 1),
                "verdict": (f"accumulating ({n}/{self.MIN_COHORTS} weekly cohorts) — not enough yet"
                            if accumulating else
                            f"measuring: FX-trend net Sharpe {sharpe} (annualized), win rate "
                            f"{round(100 * wins / n, 1)}% over {n} weeks")}
