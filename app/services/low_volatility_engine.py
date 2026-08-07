"""Low-volatility / betting-against-beta (BAB) factor sleeve — the net-new test candidate that replaced
the retired earnings-vol condor sleeve.

Institutional pedigree: the low-volatility anomaly (Haugen; AQR's Frazzini-Pedersen BAB) — low-beta / low-
vol assets earn higher RISK-ADJUSTED returns than high-beta. The full BAB is a levered long-low-beta /
short-high-beta spread; a $10k unlevered retail book can't run that, so this is the honest replicable
version: hold a basket of liquid low-vol ETFs, INVERSE-VOLATILITY weighted (more capital to the lower-vol
names — the risk-parity / low-vol construction, not equal-weight buy-and-hold), rebalanced in WHOLE shares.

Long-only, unlevered, EQUITY/ETF only — which is exactly why it can be validated in this SIM (it prices
whole-share equity fills correctly, unlike the atomic condor closes that broke the earnings sleeve). Gated
OFF by GREYLINE_LOW_VOL_ENABLED — it does NOT arm itself; forward-tested under the pre-registered edge-proof
protocol before it earns conviction. Mirrors the trend sleeve's plan/rebalance mechanics exactly.
"""

import csv
import math
import statistics
from datetime import datetime
from os import getenv
from pathlib import Path


class LowVolatilityEngine:

    HIST = Path("app/data/historical")
    # liquid, whole-share-affordable low-vol ETFs: US large-cap min-vol / S&P 500 low-vol / international
    # min-vol / US mid-cap min-vol. Different sleeves of the same factor -> real diversification within it.
    BASKET = ["USMV", "SPLV", "EFAV", "XMLV"]
    VOL_LOOKBACK = 60           # trailing trading days for realized-vol weighting
    REBALANCE_MIN_USD = 150.0   # don't churn on tiny drifts (same threshold as the trend sleeve)
    MAX_STALE_DAYS = 4          # a stalled daily refresh must not be traded on

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_LOW_VOL_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _alloc(self):
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            b = SleeveCapitalBudgetEngine.budget_usd("low_vol")
            if b and b > 0:
                return b
        except Exception:
            pass
        try:
            return float(getenv("GREYLINE_LOW_VOL_ALLOC_USD", "") or 2000.0)
        except (TypeError, ValueError):
            return 2000.0

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

    def _held(self, pos_engine, sym):
        rj = (pos_engine.get_positions().get("response_json") or {})
        for p in (rj.get("Positions") or []):
            if str(p.get("Symbol")).upper() == sym and p.get("AssetType") == "STOCK":
                return int(self._f(p.get("Quantity")))
        return 0

    def _realized_vol(self, sym):
        """Annualized trailing realized vol from the daily-close CSV, or None if insufficient/stale — never
        weight on a window that ends days in the past (a stalled refresh)."""
        closes = self._closes(sym)
        if len(closes) < self.VOL_LOOKBACK + 1:
            return None
        ds = sorted(closes)
        try:
            age = (datetime.utcnow().date() - datetime.fromisoformat(ds[-1]).date()).days
            if age > self.MAX_STALE_DAYS:
                return None
        except (ValueError, TypeError):
            return None
        px = [closes[d] for d in ds[-(self.VOL_LOOKBACK + 1):]]
        rets = [(px[i] / px[i - 1] - 1) for i in range(1, len(px)) if px[i - 1] > 0]
        if len(rets) < self.VOL_LOOKBACK // 2:
            return None
        sd = statistics.pstdev(rets)
        return round(sd * (252 ** 0.5), 4) if sd > 0 else None

    def _weights(self):
        """Inverse-volatility weights over the names with usable vol; equal-weight fallback if none have it.
        Returns ({sym: weight}, {sym: vol|None})."""
        vols = {s: self._realized_vol(s) for s in self.BASKET}
        usable = {s: v for s, v in vols.items() if v and v > 0}
        if not usable:
            return {}, vols
        inv = {s: 1.0 / v for s, v in usable.items()}
        tot = sum(inv.values())
        return {s: inv[s] / tot for s in inv}, vols

    def plan(self):
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
        q = TradeStationQuoteLiveEngine()
        pos = TradeStationPositionsLiveEngine()
        alloc = self._alloc()
        weights, vols = self._weights()
        legs, invested = [], 0.0
        for sym in self.BASKET:
            bid, ask, last = self._quote(q, sym)
            w = weights.get(sym)
            held = self._held(pos, sym)
            if w is None:
                # no usable vol (insufficient/stale history) -> no target; leave any existing position alone
                legs.append({"symbol": sym, "skipped": "no usable realized-vol (insufficient/stale history)",
                             "held": held, "vol": vols.get(sym)})
                continue
            px = last or ask or bid
            slot = alloc * w
            target = int(math.floor(slot / px)) if px > 0 else 0
            invested += target * px
            legs.append({"symbol": sym, "vol": vols.get(sym), "weight": round(w, 4), "last": round(px, 2),
                         "bid": bid, "ask": ask, "held": held, "slot_usd": round(slot, 2),
                         "target_shares": target, "delta_shares": target - held,
                         "delta_usd": round((target - held) * px, 2)})
        return {"status": "LOW_VOL_PLAN", "alloc_usd": round(alloc, 2),
                "weighting": "inverse_volatility", "deployed_usd": round(invested, 2),
                "names_weighted": len(weights), "of": len(self.BASKET), "legs": legs}

    def run_cycle(self, is_regular_session=True, dry_run=False):
        if not self.enabled():
            return {"status": "LOW_VOL_DISABLED", "acted": False}
        if not is_regular_session:
            return {"status": "LOW_VOL_MARKET_CLOSED", "acted": False}
        p = self.plan()
        # make this sleeve's fills VISIBLE to the edge court (it books straight to the broker, so it
        # writes to none of the court's other ledgers). Broker-confirmed FIFO; safe on a degraded read.
        try:
            from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
            SleeveTradeLedgerEngine().reconcile_plan("low_vol", p.get("legs"))
        except Exception:
            pass
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
        book = TradeStationSimBookingEngine()
        # PER-SLEEVE DEPLOYMENT CAP: this sleeve's own value can't exceed its budget (x buffer).
        _deployed = sum(max(0, int(lg.get("held") or 0)) * (lg.get("last") or 0) for lg in p["legs"])
        buy_headroom = SleeveCapitalBudgetEngine.deployment_headroom_usd("low_vol", _deployed)
        acts, skipped = [], []
        for leg in p["legs"]:
            d = leg.get("delta_shares")
            if not d:
                continue
            # sells (rebalance down) always act; buys respect the churn threshold
            if d > 0 and abs(leg["delta_usd"]) < self.REBALANCE_MIN_USD:
                continue
            action = "BUY" if d > 0 else "SELL"
            qty = abs(d)
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
            if action == "SELL":
                try:
                    from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                    BrokerProtectiveStopEngine().clear_stop(leg["symbol"])
                except Exception:
                    pass
            r = book.place_order(leg["symbol"], qty, action=action, order_type="Limit",
                                 limit_price=limit, tif="DAY")
            try:
                from app.services.execution_log_engine import ExecutionLogEngine
                ExecutionLogEngine().record("low_vol", leg["symbol"], action, (qty if d > 0 else -qty), limit,
                                            leg["bid"], leg["ask"], r.get("order_id"))
            except Exception:
                pass
            acts.append({"symbol": leg["symbol"], "action": action, "qty": qty, "limit": limit,
                         "ok": r.get("ok"), "order_id": r.get("order_id")})
        return {"status": "LOW_VOL_REBALANCED" if not dry_run else "LOW_VOL_DRYRUN",
                "acted": bool(acts and not dry_run), "actions": acts, "skipped": skipped,
                "deployed_usd": p["deployed_usd"]}

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "enabled": self.enabled(),
                "basket": self.BASKET, "weighting": "inverse_volatility",
                "alloc_usd": round(self._alloc(), 2), "plan": self.plan(),
                "status": "LOW_VOLATILITY_STATUS"}
