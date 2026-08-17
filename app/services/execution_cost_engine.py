"""Per-sleeve execution-cost profile — the discipline: know what the spread costs you, per strategy.

When edges are this small, the spread you cross is the difference between profit and loss (the MRNA
condor that backtested fine was 28% round-trip cost = not viable). This measures the round-trip
SPREAD each strategy pays, live, so you can hold it up against each sleeve's edge (/edge-persistence)
and cut any sleeve whose cost eats its edge.

HONEST SCOPE: this is the round-trip spread you cross per trade (structural execution cost), from
LIVE quotes — NOT realized per-fill slippage vs the order-time mid. That precise number requires
instrumenting the order path (log the mid at placement, reconcile against the fill), which is the v2
and is best done AFTER THE CLOSE, not on a live trading day. Read-only; it never trades.
"""

from datetime import datetime


class ExecutionCostEngine:

    # sleeves that trade a fixed instrument set (profiled even when flat)
    FIXED = {
        "carry": ["SVXY"],
        "trend": ["QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"],
        "tbill": ["SGOV"],
    }
    CONCERN_BPS = 30.0        # round-trip cost above this is a drag on a small edge
    NONVIABLE_BPS = 100.0     # ... above this, execution likely eats the edge entirely

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _quote(self, q, sym):
        rj = (q.get_quote(sym).get("response_json") or {})
        row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
        return self._f(row.get("Bid")), self._f(row.get("Ask"))

    def _held_by_sleeve(self):
        """Current option (premium) and other-equity (momentum) symbols, from live positions."""
        out = {"premium": [], "momentum": []}
        try:
            from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
            fixed = {s for lst in self.FIXED.values() for s in lst}
            for p in ((TradeStationPositionsLiveEngine().get_positions().get("response_json") or {})
                      .get("Positions") or []):
                sym = str(p.get("Symbol") or "")
                if str(p.get("AssetType")).upper() in ("STOCKOPTION", "OPTION"):
                    out["premium"].append(sym)
                elif sym.split()[0] not in fixed:
                    out["momentum"].append(sym)
        except Exception:
            pass
        return out

    def _round_trip_bps(self, bid, ask):
        if not bid or not ask or bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2.0
        return round((ask - bid) / mid * 1e4, 1)      # full spread = round-trip cross cost

    def profile(self):
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        q = TradeStationQuoteLiveEngine()
        held = self._held_by_sleeve()
        sleeves = dict(self.FIXED)
        sleeves["premium"] = held["premium"]
        sleeves["momentum"] = held["momentum"]

        out = {}
        for sleeve, syms in sleeves.items():
            legs = []
            for s in syms:
                bid, ask = self._quote(q, s)
                rt = self._round_trip_bps(bid, ask)
                if rt is not None:
                    legs.append({"symbol": s, "round_trip_bps": rt, "bid": bid, "ask": ask})
            if not legs:
                out[sleeve] = {"instruments": 0, "note": "flat / no live quote"}
                continue
            costs = [l["round_trip_bps"] for l in legs]
            avg = round(sum(costs) / len(costs), 1)
            worst = max(costs)
            flag = ("NON-VIABLE — cost likely eats the edge" if worst >= self.NONVIABLE_BPS
                    else "COSTLY — watch cost vs edge" if avg >= self.CONCERN_BPS
                    else "cheap")
            out[sleeve] = {"instruments": len(legs), "avg_round_trip_bps": avg,
                           "worst_round_trip_bps": worst, "flag": flag, "legs": legs}
        return {"timestamp": datetime.utcnow().isoformat(), "sleeves": out,
                "note": ("round-trip SPREAD crossed per trade, from live quotes (structural cost). "
                         "NOT realized per-fill slippage vs order-time mid — that is the v2 (order-path "
                         "instrumentation, best done after the close). Pair with /edge-persistence: a "
                         "sleeve whose cost here exceeds its edge there should be retired."),
                "status": "EXECUTION_COST_PROFILE"}
