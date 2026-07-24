"""Measure what the exit-pricing change actually SAVED — turn a projection into evidence.

The exit engine claims that pricing a SELLTOCLOSE as a limit beats dumping it at market. That
claim is only worth anything if it is measured. This engine is the exit-side twin of the entry
reconciler: for every exit order the manager places, it records the decision context, then when
the order fills it reads the realized price and computes two things:

  realized_vs_mid    = fill_price - decision_mid
                       for a SELL, POSITIVE means we sold ABOVE the mid — spread captured, not paid.

  captured_vs_market = fill_price - decision_bid
                       the counterfactual. A naked market sell hits the bid, so decision_bid is
                       what the OLD behaviour would have gotten. This is the actual dollars the
                       change added (or cost), per contract, versus what we used to do.

Both are in option points; multiply by 100 x contracts for dollars. The panel accumulates so the
verdict comes from realized fills, not from the pricing model that produced them — the same
discipline the rest of GreyLine holds itself to (measure, don't assume).

This does NOT retune anything. Unlike the entry loop, there is no free knob to turn on the exit
side — urgency is dictated by the doctrine, not chosen for fill economics. Its job is purely to
tell the truth about whether the change is helping, per urgency tier and per quote source.
"""

import json
from datetime import datetime
from pathlib import Path


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class OptionsExitReconcilerEngine:

    PENDING = Path("app/data/options_paper_trading/pending_exit_orders.jsonl")
    PANEL = Path("app/data/research/exit_execution_panel.jsonl")
    FILLED_TOKENS = ("filled",)
    DEAD_TOKENS = ("cancel", "reject", "expired", "broken", "outofmarket")

    # ------------------------------------------------------------ recording

    def record_pending(self, rec):
        """Called by book_option_close after it places an exit order. One line per order."""
        oid = rec.get("order_id")
        if not oid:
            return {"status": "NO_ORDER_ID_NOT_RECORDED"}
        try:
            self.PENDING.parent.mkdir(parents=True, exist_ok=True)
            with open(self.PENDING, "a") as f:
                f.write(json.dumps({**rec, "recorded_at": datetime.utcnow().isoformat()}) + "\n")
        except Exception as e:
            return {"status": "PENDING_WRITE_FAILED", "error": str(e)[:100]}
        return {"status": "EXIT_PENDING_RECORDED", "order_id": oid}

    def _read_jsonl(self, path):
        out = []
        try:
            for ln in path.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            return []
        return out

    def _resolved_ids(self):
        return {r.get("order_id") for r in self._read_jsonl(self.PANEL)}

    # ------------------------------------------------------------ fill read

    @staticmethod
    def _fill_price(order, fallback):
        legs = order.get("Legs") or [{}]
        leg = legs[0] if legs else {}
        for v in (order.get("FilledPrice"), leg.get("ExecutionPrice"),
                  leg.get("AvgFillPrice"), order.get("AverageFilledPrice")):
            p = _f(v)
            if p > 0:
                return p
        return fallback

    # ------------------------------------------------------------ reconcile

    def reconcile(self):
        pending = [r for r in self._read_jsonl(self.PENDING) if r.get("order_id")]
        resolved = self._resolved_ids()
        todo = [r for r in pending if r.get("order_id") not in resolved]
        if not todo:
            return {"timestamp": datetime.utcnow().isoformat(), "pending": 0, "resolved_now": 0,
                    "status": "NO_PENDING_EXIT_ORDERS"}

        try:
            from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine
            orders = (TradeStationOrdersLiveEngine().get_orders().get("response_json") or {}).get("Orders") or []
        except Exception as e:
            return {"status": "EXIT_RECONCILE_DEGRADED", "error": str(e)[:100]}
        by_id = {str(o.get("OrderID")): o for o in orders}

        filled = dead = still_working = 0
        rows = []
        for r in todo:
            oid = str(r.get("order_id"))
            o = by_id.get(oid)
            if not o:
                still_working += 1        # not yet visible / GTC still resting — leave pending
                continue
            status = str(o.get("StatusDescription") or o.get("Status") or "").lower()
            if any(t in status for t in self.FILLED_TOKENS):
                fill = self._fill_price(o, r.get("limit_price") or r.get("decision_mid"))
                rows.append(self._resolve_row(r, fill, status))
                filled += 1
            elif any(t in status for t in self.DEAD_TOKENS):
                rows.append(self._resolve_row(r, None, status))   # unfilled: no execution price
                dead += 1
            else:
                still_working += 1

        if rows:
            try:
                self.PANEL.parent.mkdir(parents=True, exist_ok=True)
                with open(self.PANEL, "a") as f:
                    for row in rows:
                        f.write(json.dumps(row) + "\n")
            except Exception as e:
                return {"status": "PANEL_WRITE_FAILED", "error": str(e)[:100]}

        return {"timestamp": datetime.utcnow().isoformat(),
                "pending": len(todo), "resolved_now": filled + dead,
                "filled": filled, "unfilled_dead": dead, "still_working": still_working,
                "status": "EXIT_RECONCILE_COMPLETE"}

    def _resolve_row(self, r, fill_price, status):
        mid = _f(r.get("decision_mid"))
        bid = _f(r.get("decision_bid"))
        ask = _f(r.get("decision_ask"))
        row = {
            "order_id": r.get("order_id"), "option_symbol": r.get("option_symbol"),
            "contracts": r.get("contracts"), "reason": r.get("reason"),
            "urgency": r.get("urgency"), "order_type": r.get("order_type"),
            "quote_source": r.get("quote_source"), "forced_market": r.get("forced_market"),
            "decision_mid": round(mid, 4) if mid else None,
            "decision_bid": round(bid, 4) if bid else None,
            "decision_ask": round(ask, 4) if ask else None,
            "spread_pct_of_mid": round((ask - bid) / mid * 100, 2) if (mid and ask and bid) else None,
            "status_desc": status, "resolved_at": datetime.utcnow().isoformat(),
        }
        if fill_price and fill_price > 0:
            row.update({
                "filled": True, "fill_price": round(fill_price, 4),
                # SELL: positive = sold above the mid (spread captured)
                "realized_vs_mid": round(fill_price - mid, 4) if mid else None,
                # vs the OLD naked-market behaviour (which hits the bid), per contract
                "captured_vs_market": round(fill_price - bid, 4) if bid else None,
                "captured_vs_market_usd": round((fill_price - bid) * 100 * _f(r.get("contracts")), 2)
                if bid else None,
            })
        else:
            row.update({"filled": False, "fill_price": None, "realized_vs_mid": None,
                        "captured_vs_market": None, "captured_vs_market_usd": None})
        return row

    # ------------------------------------------------------------ verdict

    def status(self):
        panel = [r for r in self._read_jsonl(self.PANEL) if r.get("filled")]
        pending_open = len([r for r in self._read_jsonl(self.PENDING)
                            if r.get("order_id") not in self._resolved_ids()])
        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "filled_exits_measured": len(panel),
            "pending_exits": pending_open,
        }
        if not panel:
            out.update({"verdict": "NO_FILLED_EXITS_YET",
                        "note": ("accrues as priced exits fill; measures realized price vs mid and "
                                 "vs the old naked-market-sell counterfactual (the bid)")})
            return out

        def _avg(key, rows):
            vals = [r[key] for r in rows if r.get(key) is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        total_usd = round(sum(r.get("captured_vs_market_usd") or 0 for r in panel), 2)
        by_urgency = {}
        for u in ("patient", "urgent"):
            rows = [r for r in panel if r.get("urgency") == u]
            if rows:
                by_urgency[u] = {"n": len(rows),
                                 "avg_realized_vs_mid": _avg("realized_vs_mid", rows),
                                 "avg_captured_vs_market": _avg("captured_vs_market", rows)}
        out.update({
            "avg_realized_vs_mid": _avg("realized_vs_mid", panel),
            "avg_captured_vs_market_per_contract": _avg("captured_vs_market", panel),
            "total_captured_vs_market_usd": total_usd,
            "by_urgency": by_urgency,
            "by_quote_source": {
                src: len([r for r in panel if r.get("quote_source") == src])
                for src in {r.get("quote_source") for r in panel}},
            "verdict": ("EXITS_BEATING_MARKET" if (_avg("captured_vs_market", panel) or 0) > 0
                        else "EXITS_NOT_BEATING_MARKET"),
            "reading": ("captured_vs_market > 0 means priced exits are selling above the bid a "
                        "naked market order would have hit — the change is paying off"),
        })
        return out
