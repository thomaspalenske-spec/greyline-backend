"""Futures TSMOM SHADOW — the REAL managed-futures test, with ZERO capital.

GreyLine's managed_futures sleeve trades ETF PROXIES (DBC/GLDM/TLT/...). This measures the genuine article:
time-series momentum (TSMOM) on the 19 continuous FUTURES the alt-asset scan added — long each future whose
12-month trailing return is positive, short each negative, equal-weight, rebalanced monthly. That long/short
diversified structure is the classic managed-futures diversifier (historically positive in equity crises).

Futures plumbing that a measurement actually needs (vs an ETF proxy):
  * continuous @ROOT bars — TS's back/ratio-adjusted series, so the % return is ROLL-INCLUSIVE and tradeable
    (no roll accounting needed for a return measurement). Kept current by AltAssetUniverseEngine.refresh_if_due.
  * live @ROOT quotes for settlement (verified they resolve via the standard quotes endpoint).
  * % returns, not dollars — so contract point-value / tick / margin (the LIVE-execution plumbing) is NOT
    needed to MEASURE the edge; it's needed only to ARM it, which waits on this verdict.

Monthly non-overlapping cohorts, live settlement, net of cost, judged on the live edge court's bar
(verdict_from_returns, min-N). NO orders, NO budget.
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


class FuturesTsmomShadowEngine:

    STATE = Path("app/data/futures_tsmom_shadow")
    OPEN = STATE / "open_cohort.json"
    CLOSED = STATE / "closed_cohorts.jsonl"

    LOOKBACK = 252                # 12-month TSMOM signal (the classic managed-futures lookback)
    HOLD_DAYS = 21               # monthly non-overlapping hold (matches the managed-futures cadence)
    MIN_COHORTS = 6              # ~6 months of monthly cohorts before the verdict is trustworthy
    PERIODS_PER_YEAR = 12

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_FUTURES_TSMOM_SHADOW", "true") or "true").strip().lower() == "true"

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

    # ---- universe + TSMOM signal (from the continuous @ROOT bars) ------------------------------
    def _instruments(self):
        try:
            from app.services.alt_asset_universe_engine import AltAssetUniverseEngine
            out = []
            for i in AltAssetUniverseEngine.all():
                if i["asset_class"] == "futures" and AltAssetUniverseEngine.bar_path(i["key"]).exists():
                    out.append((i["key"], i["ts_symbol"]))
            return out
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
        """TSMOM: long each future with positive 12-month trailing return, short each negative. Equal-weight."""
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
        """Settle a matured monthly cohort (long/short, live quotes), then open a fresh NON-OVERLAPPING TSMOM
        cohort across all futures. NO orders, NO budget."""
        if not self.enabled():
            return {"status": "FUT_TSMOM_SHADOW_DISABLED", "acted": False}
        # THE RULE: only open/settle when it could actually have executed on TradeStation. Futures trade ~24h,
        # so the non-tradeable window is the weekend/holiday close (not equity RTH). Fail-closed defers.
        from app.services.shadow_tradeability_gate import futures_fx_session_open
        session = futures_fx_session_open()
        cost = self._cost_roundtrip()
        cohorts = self._load_open()
        closed_now, still_open = [], []

        for co in cohorts:
            legs = co.get("legs", [])
            if self._biz_days_elapsed(co.get("opened")) < self.HOLD_DAYS:
                still_open.append(co)
                continue
            if not session:
                still_open.append(co)               # matured, but settle only when the market is open -> next session
                continue
            prices = self._live_prices([l["ts_symbol"] for l in legs])
            settled = []
            for leg in legs:
                px = prices.get(leg["ts_symbol"])
                ec = self._f2(leg.get("entry_close"))
                if px and ec and ec > 0:
                    g = (px / ec - 1.0) if leg["side"] == "BUY" else (ec / px - 1.0)   # long/short
                    settled.append({**leg, "exit_close": round(px, 6), "gross_return": round(g, 6)})
            if len(settled) < max(3, int(0.6 * len(legs))):        # need most legs priced, not a partial book
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
        if not still_open and session:              # non-overlapping AND only when the market is open
            picks = self._signal()
            live = self._live_prices([p["ts_symbol"] for p in picks])
            legs = []
            for p in picks:
                entry = live.get(p["ts_symbol"])
                if entry:
                    legs.append({**p, "entry_close": round(entry, 6)})
            if len(legs) >= 5:                                     # a real diversified book, not a few names
                opened = {"opened": self._today().isoformat(), "opened_at": datetime.utcnow().isoformat(),
                          "n_legs": len(legs), "n_long": sum(1 for l in legs if l["side"] == "BUY"), "legs": legs}
                still_open.append(opened)

        self._save_open(still_open)
        return {"status": "FUT_TSMOM_SHADOW_MARKED", "acted": bool(closed_now or opened),
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
                pct = round(100 * unreal, 2) if unreal is not None else None
                rows.append({"symbol": leg["symbol"], "ts_symbol": leg["ts_symbol"], "side": leg["side"],
                             "entry_date": co.get("opened"), "entry_close": round(ec, 6) if ec else None,
                             "live_last": round(cur, 6) if cur else None, "unrealized_pct": pct,
                             "trailing_return_pct": round(100 * self._f2(leg.get("trailing_return") or 0), 1),
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
        from app.services.shadow_contract_sizing import enrich_open_rows
        positions = enrich_open_rows(self.open_positions(), dollars=False)  # % is the measure; per-contract $ deferred until arm
        base = {"timestamp": datetime.utcnow().isoformat(), "shadow_enabled": self.enabled(),
                "engine": "FuturesTsmomShadowEngine", "universe_size": len(self._instruments()),
                "cohorts_closed": n, "min_cohorts": self.MIN_COHORTS,
                "rigorous_verdict": _rigorous_verdict(rets, self.MIN_COHORTS),
                "open_cohorts": len(self._load_open()), "open_positions": positions,
                "signal": f"TSMOM · {self.LOOKBACK}d trailing sign · long/short equal-weight · monthly",
                "hold_days": self.HOLD_DAYS, "cost_roundtrip_bps": round(self._cost_roundtrip() * 10000, 2),
                "note": ("ZERO-capital TSMOM forward-test on the CONTINUOUS FUTURES — the real managed-futures "
                         "diversifier vs today's ETF proxies. Long/short, monthly, judged on the court's bar. "
                         "% returns (roll-inclusive continuous bars), so no contract-sizing plumbing needed to "
                         "MEASURE — only to ARM. NO orders/budget.")}
        if n == 0:
            return {**base, "status": "FUT_TSMOM_SHADOW_NO_DATA",
                    "verdict": (f"{len(positions)} open ({sum(1 for p in positions if p['side']=='BUY')} long / "
                                f"{sum(1 for p in positions if p['side']=='SELL')} short) — first monthly cohort "
                                f"settles ~{self.HOLD_DAYS} biz days after opening" if positions else
                                "no cohorts yet — the first opens next mark across the futures TSMOM book")}
        eq = 1.0
        for r in rets:
            eq *= (1 + r)
        sd = self._stdev(rets)
        mean = sum(rets) / n
        sharpe = round(mean / sd * math.sqrt(self.PERIODS_PER_YEAR), 2) if sd else 0.0
        wins = sum(1 for r in rets if r > 0)
        accumulating = n < self.MIN_COHORTS
        return {**base,
                "status": "FUT_TSMOM_SHADOW_ACCUMULATING" if accumulating else "FUT_TSMOM_SHADOW_MEASURING",
                "cumulative_return_pct": round(100 * (eq - 1), 2),
                "avg_net_return_per_month_bps": round(mean * 10000, 2),
                "annualized_sharpe": sharpe, "win_rate_pct": round(100 * wins / n, 1),
                "verdict": (f"accumulating ({n}/{self.MIN_COHORTS} monthly cohorts) — not enough yet"
                            if accumulating else
                            f"measuring: futures-TSMOM net Sharpe {sharpe} (annualized), win rate "
                            f"{round(100 * wins / n, 1)}% over {n} months — the REAL managed-futures read")}
