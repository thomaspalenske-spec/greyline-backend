"""Live volatility term-structure CARRY sleeve — harvest the VIX roll, defined-risk, regime-gated.

The backtest (VolTermStructureCarryResearchEngine) established the honest shape: a REAL but MODEST
edge (Sharpe ~0.5, CAGR ~6.7% vol-targeted to 12%, max DD -23% over 15y through every crash). It
survives only because it is (1) regime-gated — SHORT vol ONLY in contango, FLAT in backwardation, so
the curve inversion flips it out before the worst of a spike — and (2) sized small by vol-targeting.

This engine trades that live, conservatively:
  * SIGNAL from the live term structure: contango when VIX < VIX3M. Backwardation -> exit to cash.
  * INSTRUMENT = LONG SVXY (-0.5x short-vol ETF). Defined-risk (a long ETF can't lose more than the
    stake — unlike naked short VIXY, which is how people went bankrupt). No borrow, no margin call.
  * SIZE = vol-target ~12%/yr on a SMALL alloc slice, capped at 1x, whole shares. Never the account.
  * HARD STOP: if SVXY falls STOP_PCT from the position's average price, exit — a backstop under the
    regime gate.
  * SOURCE OF TRUTH for the held size is the LIVE broker position, never a ledger count.
Gated OFF by GREYLINE_VOL_CARRY_ENABLED — this is short-vol; it does not arm itself.
"""

import csv
import math
import statistics
import time
from datetime import datetime
from os import getenv
from pathlib import Path


class VolTermStructureCarryEngine:

    SYMBOL = "SVXY"
    HIST = Path("app/data/historical/SVXY_daily.csv")
    VOL_TARGET = 0.12          # annualized target for the sleeve
    MAX_W = 1.0                # never lever past the alloc
    STOP_PCT = 0.15            # exit if SVXY falls this far from avg price (disaster backstop)
    REBALANCE_MIN_USD = 150.0  # no churn for small deltas
    RV_WINDOW = 20

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_VOL_CARRY_ENABLED", "") or "").strip().lower() == "true"

    @classmethod
    def _alloc(cls):
        # %-of-equity budget (scales with the account, clamped to live deployable cash). Falls back
        # to the legacy static-dollar env var only if the central resolver is unavailable.
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            return SleeveCapitalBudgetEngine.budget_usd("vol_carry")
        except Exception:
            pass
        try:
            return float(getenv("GREYLINE_VOL_CARRY_ALLOC_USD", "") or 2000.0)
        except (TypeError, ValueError):
            return 2000.0

    # ---- signal --------------------------------------------------------------------------------

    def _idx(self, q, sym):
        rj = (q.get_quote(sym).get("response_json") or {})
        row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
        return self._f(row.get("Last") or row.get("Close"))

    def signal(self, q):
        vix, vix3m = self._idx(q, "$VIX.X"), self._idx(q, "$VIX3M.X")
        if vix <= 0 or vix3m <= 0:
            return {"ok": False, "reason": "no term-structure quote"}
        ratio = vix / vix3m
        return {"ok": True, "vix": vix, "vix3m": vix3m, "ratio": round(ratio, 4),
                "contango": ratio < 1.0,
                "state": "CONTANGO_HARVEST" if ratio < 1.0 else "BACKWARDATION_STAND_ASIDE"}

    # ---- SVXY realized vol (for sizing) --------------------------------------------------------

    def _refresh_bars(self):
        """Best-effort: keep SVXY_daily.csv current so the vol estimate isn't stale."""
        try:
            today = datetime.utcnow().date().isoformat()
            if self.HIST.exists():
                last = None
                with open(self.HIST) as f:
                    for r in csv.DictReader(f):
                        last = str(r.get("date"))[:10]
                if last and last >= today:
                    return
            import requests
            tok = getenv("TRADESTATION_ACCESS_TOKEN", "")
            base = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
            if not tok:
                return
            r = requests.get(f"{base.rstrip('/')}/v3/marketdata/barcharts/{self.SYMBOL}",
                             params={"unit": "Daily", "barsback": 120},
                             headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
                             timeout=30)
            bars = (r.json() or {}).get("Bars") or [] if r.status_code == 200 else []
            rows = []
            for b in bars:
                ts = b.get("TimeStamp") or b.get("Timestamp")
                try:
                    o, h, l, c = float(b["Open"]), float(b["High"]), float(b["Low"]), float(b["Close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if ts and min(o, h, l, c) > 0:
                    rows.append((str(ts)[:10], o, h, l, c, int(self._f(b.get("TotalVolume") or b.get("Volume")))))
            if len(rows) < self.RV_WINDOW + 2:
                return
            # MERGE, never overwrite: a refresh fetches only recent bars, so writing just those would
            # DESTROY the full history archive (it once truncated 3,724 bars -> 120). Union by date,
            # fetched bars winning on overlap, so the file only ever grows / updates.
            merged = {}
            if self.HIST.exists():
                with open(self.HIST) as f:
                    for r in csv.DictReader(f):
                        d = str(r.get("date"))[:10]
                        try:
                            merged[d] = (d, float(r["open"]), float(r["high"]), float(r["low"]),
                                         float(r["close"]), int(self._f(r.get("volume"))))
                        except (KeyError, TypeError, ValueError):
                            continue
            for row in rows:
                merged[row[0]] = row
            out = [merged[d] for d in sorted(merged)]
            self.HIST.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.HIST.with_suffix(".csv.tmp")
            with open(tmp, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "open", "high", "low", "close", "volume"])
                for row in out:
                    w.writerow(row)
            tmp.replace(self.HIST)
        except Exception:
            pass

    def _realized_vol(self):
        try:
            closes = []
            with open(self.HIST) as f:
                for r in csv.DictReader(f):
                    c = self._f(r.get("close"))
                    if c > 0:
                        closes.append(c)
            if len(closes) < self.RV_WINDOW + 1:
                return None
            seg = closes[-(self.RV_WINDOW + 1):]
            rets = [math.log(seg[i + 1] / seg[i]) for i in range(len(seg) - 1)]
            sd = statistics.pstdev(rets) or 1e-9
            return sd * math.sqrt(252)
        except Exception:
            return None

    def _target_weight(self):
        rv = self._realized_vol()
        if not rv:
            return self.MAX_W * 0.5, None      # conservative default if vol unknown
        return min(self.MAX_W, self.VOL_TARGET / rv), round(rv, 3)

    # ---- live broker position (source of truth) ------------------------------------------------

    def _held(self, pos_engine):
        rj = (pos_engine.get_positions().get("response_json") or {})
        for p in (rj.get("Positions") or []):
            if str(p.get("Symbol")).upper() == self.SYMBOL and p.get("AssetType") == "STOCK":
                return int(self._f(p.get("Quantity"))), self._f(p.get("AveragePrice"))
        return 0, 0.0

    # ---- plan / act ----------------------------------------------------------------------------

    def plan(self):
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
        q = TradeStationQuoteLiveEngine()
        sig = self.signal(q)
        if not sig["ok"]:
            return {"status": "NO_SIGNAL", **sig}
        self._refresh_bars()
        weight, rv = self._target_weight()
        alloc = self._alloc()

        rj = (q.get_quote(self.SYMBOL).get("response_json") or {})
        row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
        bid, ask = self._f(row.get("Bid")), self._f(row.get("Ask"))
        last = self._f(row.get("Last") or row.get("Close"))
        px = last or ask or bid
        if px <= 0:
            return {"status": "NO_QUOTE", **sig}

        held, avg = self._held(TradeStationPositionsLiveEngine())
        stopped = bool(held > 0 and avg > 0 and (px / avg - 1.0) <= -self.STOP_PCT)

        if not sig["contango"] or stopped:
            target_shares = 0                                  # backwardation or stop -> flat
        else:
            target_shares = int(math.floor((weight * alloc) / px))
        delta = target_shares - held
        return {"status": "VOL_CARRY_PLAN", **sig, "svxy": px, "bid": bid, "ask": ask,
                "realized_vol": rv, "target_weight": round(weight, 3), "alloc_usd": alloc,
                "held_shares": held, "avg_price": avg, "stopped": stopped,
                "target_shares": target_shares, "delta_shares": delta,
                "delta_usd": round(delta * px, 2)}

    def run_cycle(self, is_regular_session=True, dry_run=False):
        if not self.enabled():
            return {"status": "VOL_CARRY_DISABLED", "acted": False}
        if not is_regular_session:
            return {"status": "VOL_CARRY_MARKET_CLOSED", "acted": False}
        p = self.plan()
        if p["status"] not in ("VOL_CARRY_PLAN",):
            return {**p, "acted": False}
        # make this single-position sleeve's fills VISIBLE to the edge court (books straight to the
        # broker). Broker-confirmed FIFO; empty-read guard makes it safe on a degraded positions read.
        try:
            from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
            SleeveTradeLedgerEngine().reconcile_plan(
                "vol_carry", [{"symbol": self.SYMBOL, "held": p.get("held_shares"), "last": p.get("svxy")}])
        except Exception:
            pass
        delta = p["delta_shares"]
        # A FULL exit (target 0 — backwardation / stop) always acts. A routine vol-target trim in
        # EITHER direction respects the churn band, so we don't pay the spread on tiny daily wiggles.
        full_exit = p["target_shares"] == 0
        if delta == 0 or (not full_exit and abs(p["delta_usd"]) < self.REBALANCE_MIN_USD):
            return {**p, "status": "VOL_CARRY_IN_BALANCE", "acted": False}
        if dry_run:
            return {**p, "status": "VOL_CARRY_DRYRUN", "acted": False,
                    "would": ("BUY" if delta > 0 else "SELL", abs(delta), self.SYMBOL)}
        action = "BUY" if delta > 0 else "SELL"
        # A SELL is rejected if a broker protective STOP still reserves the shares ("long N with N on
        # sell orders"). Clear it first; the stop engine re-places one on the remaining shares next cycle.
        if action == "SELL":
            try:
                from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                BrokerProtectiveStopEngine().clear_stop(self.SYMBOL)
            except Exception:
                pass
        # patient limit: post toward the mid to CAPTURE part of the spread instead of crossing it all
        from app.services.execution_pricing_engine import ExecutionPricingEngine
        limit = ExecutionPricingEngine.patient_limit(p["bid"], p["ask"], delta > 0)
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        r = TradeStationSimBookingEngine().place_order(self.SYMBOL, abs(delta), action=action,
                                                       order_type="Limit", limit_price=limit, tif="DAY")
        try:
            from app.services.execution_log_engine import ExecutionLogEngine
            ExecutionLogEngine().record("carry", self.SYMBOL, action, delta, limit,
                                        p["bid"], p["ask"], r.get("order_id"))
        except Exception:
            pass
        return {**p, "status": "VOL_CARRY_ORDERED", "acted": True, "action": action,
                "qty": abs(delta), "limit": limit, "ok": r.get("ok"), "order_id": r.get("order_id")}

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "armed": self.enabled(), **self.plan()}
