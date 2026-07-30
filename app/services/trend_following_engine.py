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

    def _signal(self, sym, live_last):
        """(uptrend, last, sma) using CSV history + today's live price as the latest close."""
        closes = self._closes(sym)
        if len(closes) < self.SMA:
            return None
        ds = sorted(closes)
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
        legs, invested, uptrends = [], 0.0, 0
        for sym in self.BASKET:
            bid, ask, last = self._quote(q, sym)
            sig = self._signal(sym, last)
            if sig is None:
                legs.append({"symbol": sym, "skipped": "insufficient history"})
                continue
            px = last or ask or bid
            held = self._held(pos, sym)
            target = int(math.floor(slot / px)) if (sig["uptrend"] and px > 0) else 0
            if sig["uptrend"]:
                uptrends += 1
                invested += target * px
            legs.append({"symbol": sym, "uptrend": sig["uptrend"], "last": sig["last"],
                         "sma200": sig["sma"], "bid": bid, "ask": ask, "held": held,
                         "target_shares": target, "delta_shares": target - held,
                         "delta_usd": round((target - held) * px, 2)})
        return {"status": "TREND_PLAN", "alloc_usd": self._alloc(), "slot_usd": round(slot, 2),
                "assets_in_uptrend": uptrends, "of": len(self.BASKET),
                "deployed_usd": round(invested, 2), "legs": legs}

    def run_cycle(self, is_regular_session=True, dry_run=False):
        if not self.enabled():
            return {"status": "TREND_DISABLED", "acted": False}
        if not is_regular_session:
            return {"status": "TREND_MARKET_CLOSED", "acted": False}
        p = self.plan()
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        book = TradeStationSimBookingEngine()
        acts = []
        for leg in p["legs"]:
            d = leg.get("delta_shares")
            if not d:
                continue
            # exits (sell to target, incl. downtrend->0) always act; entries respect churn threshold
            if d > 0 and abs(leg["delta_usd"]) < self.REBALANCE_MIN_USD:
                continue
            action = "BUY" if d > 0 else "SELL"
            # patient limit: post toward the mid to CAPTURE part of the spread instead of crossing it
            from app.services.execution_pricing_engine import ExecutionPricingEngine
            limit = ExecutionPricingEngine.patient_limit(leg["bid"], leg["ask"], d > 0)
            if not limit or limit <= 0:
                continue
            if dry_run:
                acts.append({"symbol": leg["symbol"], "would": action, "qty": abs(d), "limit": limit})
                continue
            # a SELL is rejected while a protective STOP reserves the shares — clear it first; the
            # stop engine re-places one on the remaining shares next cycle.
            if action == "SELL":
                try:
                    from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                    BrokerProtectiveStopEngine().clear_stop(leg["symbol"])
                except Exception:
                    pass
            r = book.place_order(leg["symbol"], abs(d), action=action, order_type="Limit",
                                 limit_price=limit, tif="DAY")
            try:
                from app.services.execution_log_engine import ExecutionLogEngine
                ExecutionLogEngine().record("trend", leg["symbol"], action, d, limit,
                                            leg["bid"], leg["ask"], r.get("order_id"))
            except Exception:
                pass
            acts.append({"symbol": leg["symbol"], "action": action, "qty": abs(d), "limit": limit,
                         "ok": r.get("ok"), "order_id": r.get("order_id")})
        return {"status": "TREND_REBALANCED" if not dry_run else "TREND_DRYRUN",
                "acted": bool(acts and not dry_run), "actions": acts,
                "assets_in_uptrend": p["assets_in_uptrend"], "deployed_usd": p["deployed_usd"]}

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "armed": self.enabled(), **self.plan()}
