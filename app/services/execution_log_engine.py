"""Realized execution-cost measurement — what we ACTUALLY paid vs the mid, per trade, per strategy.

/execution-cost estimates the spread from a live quote. This measures the real thing: at order time
the strategy engine logs the MID it decided against (bid/ask it already has); once the order fills,
we reconcile the broker's fill price against that mid. Slippage vs mid IS our true execution cost —
and it tells us whether the patient pricing is actually capturing spread (fills near the mid) or
just crossing (fills at the touch), and our fill RATE (are patient limits resting unfilled?).

Captured in the engines (which hold the decision-time quote), NOT in place_order — so the shared
all-orders path is never touched. Recording is best-effort and wrapped by callers; it can't affect
an order. Reconciliation is read-only.
"""

import json
from datetime import datetime
from pathlib import Path


class ExecutionLogEngine:

    DIR = Path("app/data/execution")
    LEDGER = DIR / "order_intent.jsonl"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def record(self, strategy, symbol, action, qty, limit, bid, ask, order_id):
        """Log the decision-time intent + mid for one order (append-only). Best-effort."""
        try:
            b, a = self._f(bid), self._f(ask)
            mid = (b + a) / 2.0 if (b and a and a >= b) else None
            self.DIR.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.utcnow().isoformat(), "strategy": strategy,
                    "symbol": str(symbol), "action": str(action), "qty": int(abs(qty)),
                    "limit": self._f(limit), "bid": b, "ask": a, "mid": mid,
                    "order_id": order_id,
                }) + "\n")
        except Exception:
            pass

    def record_fill(self, strategy, symbol, action, qty, mid, fill, order_id=None):
        """Log a COMPLETED slippage directly, when BOTH the decision mid AND the actual fill are known
        at once — e.g. a multi-leg condor close, whose single order_id doesn't join cleanly to one fill
        price. `qty` is share-equivalent (options: contracts × 100) so realized $ and notional come out
        right; bps is qty-independent. Append-only, best-effort — never affects an order."""
        try:
            m, fp = self._f(mid), self._f(fill)
            self.DIR.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.utcnow().isoformat(), "strategy": strategy, "symbol": str(symbol),
                    "action": str(action), "qty": int(abs(qty)), "mid": m, "fill_price": fp,
                    "direct": True, "order_id": order_id,
                }) + "\n")
        except Exception:
            pass

    def _intents(self):
        try:
            return [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def _broker_fills(self):
        """{order_id: fill_price} for filled orders."""
        out = {}
        try:
            from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
            for o in ((TradeStationSimBookingEngine().orders().get("response_json") or {}).get("Orders") or []):
                if str(o.get("StatusDescription")) not in ("Filled", "FLL"):
                    continue
                fp = self._f(o.get("FilledPrice")) or self._f((o.get("Legs") or [{}])[0].get("ExecutionPrice"))
                if o.get("OrderID") and fp and fp > 0:
                    out[o.get("OrderID")] = fp
        except Exception:
            pass
        return out

    def realized(self):
        """Per-strategy realized slippage vs the decision-time mid, and fill rate."""
        intents = self._intents()
        fills = self._broker_fills()
        agg = {}
        for it in intents:
            s = it.get("strategy") or "unknown"
            a = agg.setdefault(s, {"orders": 0, "filled": 0, "slip_bps_sum": 0.0,
                                   "slip_usd": 0.0, "notional": 0.0})
            a["orders"] += 1
            mid = self._f(it.get("mid"))
            # direct (record_fill) entries carry their own fill; intent entries join to a broker fill by id
            fill = self._f(it.get("fill_price")) if it.get("direct") else fills.get(it.get("order_id"))
            if not fill or not mid or mid <= 0:
                continue
            a["filled"] += 1
            sign = 1.0 if str(it.get("action", "")).upper().startswith("BUY") else -1.0
            slip_bps = sign * (fill - mid) / mid * 1e4     # + = paid worse than mid (a cost)
            notional = fill * (it.get("qty") or 0)
            a["slip_bps_sum"] += slip_bps
            a["slip_usd"] += sign * (fill - mid) * (it.get("qty") or 0)
            a["notional"] += notional
        out = {}
        for s, a in agg.items():
            out[s] = {
                "orders": a["orders"], "filled": a["filled"],
                "fill_rate_pct": round(100 * a["filled"] / max(1, a["orders"]), 1),
                "avg_slippage_bps": round(a["slip_bps_sum"] / a["filled"], 2) if a["filled"] else None,
                "realized_slippage_usd": round(a["slip_usd"], 2),
            }
        return {"timestamp": datetime.utcnow().isoformat(), "by_strategy": out,
                "note": ("slippage vs the decision-time MID: + = paid worse than mid (real cost), "
                         "~0 = patient pricing captured the spread. Low fill_rate = patient limits "
                         "resting unfilled. Reconciles logged intents against broker fill prices."),
                "status": "EXECUTION_REALIZED"}
