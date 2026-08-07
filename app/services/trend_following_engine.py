"""Live trend-following equity sleeve — GreyLine's long/flat, crash-resistant diversifier.

The backtest (TrendFollowingResearchEngine) established it: 200-DMA long/flat on a diversified ETF
basket cuts equity drawdowns roughly in half (2008 SPY -46% -> basket -2%) at a Sharpe of ~0.5 full
sample (0.77 recent). It is the best risk-adjusted, most-backtestable edge GreyLine has, and it adds
a different return driver to a book that is otherwise all short-volatility. It is NOT a clean hedge
for the carry (they correlate +0.57) — it is a diversifier, held honestly as such.

Mechanics, conservative by design:
  * SIGNAL per asset: latest close (CSV history + today's live quote) vs its own 200-day SMA. Uptrend
    -> hold; downtrend -> cash. Long/FLAT only, no shorting, no leverage.
  * SIZE: equal-weight slots (ALLOC / N) across the basket; a downtrend asset's slot sits in cash.
    Whole shares. Rebalances toward target; a churn threshold stops daily noise trading.
  * SOURCE OF TRUTH for held size is the LIVE broker position, never a ledger count.
Gated OFF by GREYLINE_TREND_ENABLED — it does not arm itself.
"""

import csv
import math
from datetime import datetime
from os import getenv
from pathlib import Path


class TrendFollowingEngine:

    HIST = Path("app/data/historical")
    # TRADEABLE basket = affordable-in-whole-shares equivalents of the backtested indices, so a $10k
    # book can hold each in whole shares. QQQM==QQQ (Nasdaq-100), GLDM==GLD (gold) — identical index,
    # cheaper share price, so the 200-DMA signal is identical to the long-history backtest. SPY/VOO/IVV
    # (~$700+) are dropped live: no cheap S&P share-class exists in the TS sandbox and one share would
    # blow the slot — US-equity beta is carried by QQQM (large growth) + IWM (small). Bonds/gold/intl/
    # commodities keep their standard tickers (already whole-share affordable).
    BASKET = ["QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"]
    SMA = 200
    REBALANCE_MIN_USD = 150.0

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_TREND_ENABLED", "") or "").strip().lower() == "true"

    @classmethod
    def _alloc(cls):
        # %-of-equity budget (scales with the account, clamped to live deployable cash). Falls back
        # to the legacy static-dollar env var only if the central resolver is unavailable.
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            return SleeveCapitalBudgetEngine.budget_usd("trend")
        except Exception:
            pass
        try:
            return float(getenv("GREYLINE_TREND_ALLOC_USD", "") or 3000.0)
        except (TypeError, ValueError):
            return 3000.0

    def _closes(self, sym):
        out = {}
        try:
            with open(self.HIST / f"{sym}_daily.csv") as f:
                for r in csv.DictReader(f):
                    c = self._f(r.get("close"))
                    if c > 0:
                        out[str(r.get("date"))[:10]] = c
        except Exception:
            return {}
        return out

    def _quote(self, q, sym):
        rj = (q.get_quote(sym).get("response_json") or {})
        row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
        return self._f(row.get("Bid")), self._f(row.get("Ask")), self._f(row.get("Last") or row.get("Close"))

    MAX_STALE_DAYS = 4          # allow a 3-day holiday weekend; beyond it the daily refresh has stalled

    def _signal(self, sym, live_last):
        """(uptrend, last, sma) using CSV history + today's live price as the latest close.

        Returns {"stale": reason} when the newest CSV bar is too old to trade on — never build a
        200-DMA decision from a window that ends days in the past and glue today's live price onto it
        (a stalled daily refresh would otherwise trade on stale bars labelled 'live')."""
        closes = self._closes(sym)
        if len(closes) < self.SMA:
            return None
        ds = sorted(closes)
        try:
            age = (datetime.utcnow().date() - datetime.fromisoformat(ds[-1]).date()).days
            if age > self.MAX_STALE_DAYS:
                return {"stale": f"newest bar {ds[-1]} is {age} calendar days old (max {self.MAX_STALE_DAYS})"}
        except (ValueError, TypeError):
            return {"stale": f"unusable newest bar date {ds[-1]!r}"}
        recent = [closes[d] for d in ds[-(self.SMA - 1):]]        # last 199 historical closes
        last = live_last if live_last > 0 else closes[ds[-1]]
        sma = (sum(recent) + last) / self.SMA                     # 199 history + today = 200
        return {"uptrend": last > sma, "last": round(last, 2), "sma": round(sma, 2)}

    def _held(self, pos_engine, sym):
        rj = (pos_engine.get_positions().get("response_json") or {})
        for p in (rj.get("Positions") or []):
            if str(p.get("Symbol")).upper() == sym and p.get("AssetType") == "STOCK":
                return int(self._f(p.get("Quantity")))
        return 0

    def plan(self):
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
        q = TradeStationQuoteLiveEngine()
        pos = TradeStationPositionsLiveEngine()
        slot = self._alloc() / len(self.BASKET)
        # CHURN GUARD: one orders read for the whole basket. A sleeve's own RESTING (unfilled) DAY limits
        # are invisible to `held`, so without this each cycle re-posts the same shortfall and the
        # duplicate limits stack until they all fill and overshoot target (observed live 2026-08-04).
        from app.services.in_flight_orders_engine import InFlightOrdersEngine
        inflight = InFlightOrdersEngine.snapshot()
        legs, invested, uptrends, stale_syms = [], 0.0, 0, []
        for sym in self.BASKET:
            bid, ask, last = self._quote(q, sym)
            sig = self._signal(sym, last)
            if sig is None:
                legs.append({"symbol": sym, "skipped": "insufficient history"})
                continue
            if sig.get("stale"):
                # Never trade this symbol on stale bars — skip it, no target (existing position untouched).
                legs.append({"symbol": sym, "skipped": f"STALE_DATA: {sig['stale']}"})
                stale_syms.append(sym)
                continue
            px = last or ask or bid
            # size against THIS sleeve's own position when per-sleeve accounting is armed (so an overlapping
            # sleeve can't claim/liquidate trend's shares); disarmed -> broker total, byte-identical to legacy.
            from app.services.sleeve_position_ledger_engine import SleevePositionLedgerEngine
            broker_total = self._held(pos, sym)                     # WHOLE broker position (for reconcile share)
            held = SleevePositionLedgerEngine.effective_held("trend", sym, broker_total)   # this sleeve's own
            inflight_net = InFlightOrdersEngine.net_working(sym, snapshot=inflight)["net"] if inflight["ok"] else 0
            effective_held = held + inflight_net
            target = int(math.floor(slot / px)) if (sig["uptrend"] and px > 0) else 0
            if sig["uptrend"]:
                uptrends += 1
                invested += target * px
            legs.append({"symbol": sym, "uptrend": sig["uptrend"], "last": sig["last"],
                         "sma200": sig["sma"], "bid": bid, "ask": ask,
                         "broker_total": broker_total, "held": held,
                         "in_flight_net": inflight_net, "effective_held": effective_held,
                         "target_shares": target, "delta_shares": target - effective_held,
                         "delta_usd": round((target - effective_held) * px, 2)})
        return {"status": "TREND_PLAN", "alloc_usd": self._alloc(), "slot_usd": round(slot, 2),
                "assets_in_uptrend": uptrends, "of": len(self.BASKET), "in_flight_ok": inflight["ok"],
                "deployed_usd": round(invested, 2), "legs": legs, "stale_symbols": stale_syms}

    def run_cycle(self, is_regular_session=True, dry_run=False):
        if not self.enabled():
            return {"status": "TREND_DISABLED", "acted": False}
        if not is_regular_session:
            return {"status": "TREND_MARKET_CLOSED", "acted": False}
        # RECONCILE-FIRST: sync confirmed held to the live broker BEFORE sizing, so the ledger "others"
        # every sleeve subtracts (and the edge court) is never stale at decision time — the reconcile-
        # after-sizing lag that let deltas explode. Also makes the sleeve's fills visible to the court.
        try:
            from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
            SleeveTradeLedgerEngine().reconcile_from_broker("trend", self.BASKET)
        except Exception:
            pass
        p = self.plan()
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        book = TradeStationSimBookingEngine()
        # PER-SLEEVE DEPLOYMENT CAP: this sleeve's own committed value can't exceed its budget (x buffer),
        # so it can't eat the whole book within the total book cap (the carry SVXY-87 failure mode).
        from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
        _deployed = sum(max(0, int(lg.get("held") or 0)) * (lg.get("last") or 0) for lg in p["legs"])
        buy_headroom = SleeveCapitalBudgetEngine.deployment_headroom_usd("trend", _deployed)
        acts, skipped = [], []
        for leg in p["legs"]:
            d = leg.get("delta_shares")
            if not d:
                continue
            # Blind on our own resting orders (degraded read) -> only a full leg exit (target 0) may act;
            # a routine buy/trim placed blind is the duplicate that stacks the churn loop.
            if not p.get("in_flight_ok", True) and leg.get("target_shares") != 0:
                skipped.append({"symbol": leg["symbol"], "reason": "orders read degraded — churn guard"})
                continue
            # exits (sell to target, incl. downtrend->0) always act; entries respect churn threshold
            if d > 0 and abs(leg["delta_usd"]) < self.REBALANCE_MIN_USD:
                continue
            action = "BUY" if d > 0 else "SELL"
            qty = abs(d)
            # SELL-CAP (safety backstop): never sell more than THIS sleeve's own broker-confirmed holding —
            # so a sizing error can't liquidate another sleeve's shares in a shared symbol or go short.
            from app.services.sleeve_position_ledger_engine import SleevePositionLedgerEngine
            if action == "SELL" and SleevePositionLedgerEngine.armed():
                from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
                own = SleeveTradeLedgerEngine().held_qty("trend", leg["symbol"])
                qty = min(qty, max(0, own))
                if qty <= 0:
                    skipped.append({"symbol": leg["symbol"], "reason": "sell-cap: no own confirmed shares"})
                    continue
            # patient limit: post toward the mid to CAPTURE part of the spread instead of crossing it
            from app.services.execution_pricing_engine import ExecutionPricingEngine
            limit = ExecutionPricingEngine.patient_limit(leg["bid"], leg["ask"], d > 0)
            if not limit or limit <= 0:
                continue
            if action == "BUY":                              # cap the buy at the sleeve's remaining budget
                if qty * limit > buy_headroom:
                    qty = int(buy_headroom / limit) if limit > 0 else 0
                if qty <= 0:
                    skipped.append({"symbol": leg["symbol"], "reason": "per-sleeve budget cap — at/over budget"})
                    continue
                buy_headroom -= qty * limit
            if dry_run:
                acts.append({"symbol": leg["symbol"], "would": action, "qty": qty, "limit": limit})
                continue
            # a SELL is rejected while a protective STOP reserves the shares — clear it first; the
            # stop engine re-places one on the remaining shares next cycle.
            if action == "SELL":
                try:
                    from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                    BrokerProtectiveStopEngine().clear_stop(leg["symbol"])
                except Exception:
                    pass
            r = book.place_order(leg["symbol"], qty, action=action, order_type="Limit",
                                 limit_price=limit, tif="DAY")
            # (per-sleeve position is tracked by the BROKER-CONFIRMED SleeveTradeLedgerEngine.reconcile_plan
            #  above — not an optimistic order-count, which drifted negative and is no longer used for sizing.)
            try:
                from app.services.execution_log_engine import ExecutionLogEngine
                ExecutionLogEngine().record("trend", leg["symbol"], action, (qty if d > 0 else -qty), limit,
                                            leg["bid"], leg["ask"], r.get("order_id"))    # ACTUAL placed qty
            except Exception:
                pass
            acts.append({"symbol": leg["symbol"], "action": action, "qty": qty, "limit": limit,
                         "ok": r.get("ok"), "order_id": r.get("order_id")})
        return {"status": "TREND_REBALANCED" if not dry_run else "TREND_DRYRUN",
                "acted": bool(acts and not dry_run), "actions": acts, "skipped": skipped,
                "in_flight_ok": p.get("in_flight_ok", True),
                "assets_in_uptrend": p["assets_in_uptrend"], "deployed_usd": p["deployed_usd"]}

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "armed": self.enabled(), **self.plan()}
