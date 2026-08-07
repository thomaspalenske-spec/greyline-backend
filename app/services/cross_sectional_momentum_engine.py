"""Cross-sectional (relative-strength) MOMENTUM sleeve — the missing AQR canonical style, built the
SIM-clean way.

Institutional pedigree: momentum is one of AQR's five style premia (value / momentum / carry / defensive /
trend) and the single most robust equity anomaly (Jegadeesh-Titman; "Value and Momentum Everywhere"). It is
DISTINCT from what GreyLine already runs: trend is TIME-SERIES (each asset vs its own history); this is
CROSS-SECTIONAL (rank assets against EACH OTHER, hold the strongest). The momentum-reversal sleeve is
SHORT-horizon contrarian — the opposite horizon; the two are the documented complementary pair.

Built survivorship-clean on purpose: single-stock momentum backtests are survivorship-biased on GreyLine's
data (delisted names' history is purged — the exact bias that inflated the momentum-reversal long side). So
the universe is a broad set of LONG-LIVED cross-asset ETFs (US/intl/EM equity, bonds, credit, gold,
commodities, REITs) — ETFs don't delist, so the rank is clean. Construction is Antonacci-style DUAL momentum:
cross-sectional RELATIVE strength (12-1 month) to pick leaders, plus an ABSOLUTE-momentum filter (only hold a
leader whose own 12-1 return is positive — else that slot goes to cash). The absolute filter is the crash
guard ("momentum has its moments").

Long-only, unlevered, whole-share ETF -> SIM-priceable and forward-testable. Gated OFF (GREYLINE_XSMOM_ENABLED);
forward-tested under the edge-proof protocol (n=25) before it earns conviction. Mirrors the low-vol/trend
sleeve mechanics; rebalances on a MONTHLY cadence (momentum is a slow signal) with a prompt exit when a held
leader falls out of the selection.
"""

import csv
import json
import math
import statistics
from datetime import datetime
from os import getenv
from pathlib import Path


class CrossSectionalMomentumEngine:

    HIST = Path("app/data/historical")
    STATE = Path("app/data/state/xs_momentum_last_rebalance.json")
    # broad, long-lived cross-asset ETFs — the rank is across ASSET CLASSES (equity/bonds/credit/real
    # assets), which is where relative-strength momentum diversifies most. All survivorship-free.
    UNIVERSE = ["QQQM", "IWM", "EFA", "EEM", "TLT", "IEF", "HYG", "GLDM", "DBC", "VNQ"]
    LOOKBACK_DAYS = 252         # ~12 months
    SKIP_DAYS = 21              # skip the most recent ~1 month (the 12-1 convention; avoids short-term reversal)
    TOP_N = 4                   # hold the strongest N that also pass the absolute filter
    MIN_ABS_MOM = 0.0           # DUAL momentum: only hold a leader whose own 12-1 return is > this (crash guard)
    REBALANCE_DAYS = 28         # monthly cadence — momentum is a slow signal; don't whipsaw
    REBALANCE_MIN_USD = 150.0   # churn floor (same as the other ETF sleeves)
    MAX_STALE_DAYS = 4

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_XSMOM_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _alloc(self):
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            b = SleeveCapitalBudgetEngine.budget_usd("xs_momentum")
            if b and b > 0:
                return b
        except Exception:
            pass
        try:
            return float(getenv("GREYLINE_XSMOM_ALLOC_USD", "") or 1500.0)
        except (TypeError, ValueError):
            return 1500.0

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

    def _momentum(self, sym):
        """12-1 month return (skip the most recent month), or None if insufficient/stale history — never
        rank on a window that ends days in the past (a stalled refresh)."""
        closes = self._closes(sym)
        if len(closes) < self.LOOKBACK_DAYS + 1:
            return None
        ds = sorted(closes)
        try:
            if (datetime.utcnow().date() - datetime.fromisoformat(ds[-1]).date()).days > self.MAX_STALE_DAYS:
                return None
        except (ValueError, TypeError):
            return None
        px = [closes[d] for d in ds]
        recent = px[-(self.SKIP_DAYS + 1)]          # ~1 month ago
        old = px[-(self.LOOKBACK_DAYS + 1)]         # ~12 months ago
        if old <= 0:
            return None
        return round(recent / old - 1.0, 4)

    def _rank(self):
        """Return (selected {sym: momentum}, all {sym: momentum|None}). Selected = the TOP_N by 12-1
        momentum that ALSO clear the absolute-momentum filter (dual momentum)."""
        moms = {s: self._momentum(s) for s in self.UNIVERSE}
        usable = {s: m for s, m in moms.items() if m is not None}
        ranked = sorted(usable.items(), key=lambda kv: kv[1], reverse=True)
        selected = {s: m for s, m in ranked if m > self.MIN_ABS_MOM}       # absolute filter
        selected = dict(list(selected.items())[: self.TOP_N])             # top N of those
        return selected, moms

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

    def plan(self):
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
        from app.services.sleeve_position_ledger_engine import SleevePositionLedgerEngine
        from app.services.in_flight_orders_engine import InFlightOrdersEngine
        q = TradeStationQuoteLiveEngine()
        pos = TradeStationPositionsLiveEngine()
        alloc = self._alloc()
        selected, moms = self._rank()
        per = (alloc / len(selected)) if selected else 0.0   # equal-weight the leaders
        # CHURN GUARD: one orders read for the whole universe — a resting DAY limit is invisible to `held`,
        # so without this a monthly-cadence sleeve could still stack duplicates on a forced-exit day.
        inflight = InFlightOrdersEngine.snapshot()
        legs, invested, held_off = [], 0.0, []
        # target legs for the selected leaders
        for sym in self.UNIVERSE:
            bid, ask, last = self._quote(q, sym)
            # size against THIS sleeve's own BROKER-CONFIRMED position (per-sleeve accounting), not the broker
            # total — so it never touches trend's shares in the overlapping ETFs. Disarmed -> broker total.
            broker_total = self._held(pos, sym)
            held = SleevePositionLedgerEngine.effective_held("xs_momentum", sym, broker_total)
            inflight_net = InFlightOrdersEngine.net_working(sym, snapshot=inflight)["net"] if inflight["ok"] else 0
            effective_held = held + inflight_net
            px = last or ask or bid
            base = {"symbol": sym, "momentum": moms.get(sym), "last": round(px, 2), "bid": bid, "ask": ask,
                    "broker_total": broker_total, "held": held, "in_flight_net": inflight_net,
                    "effective_held": effective_held}
            if sym in selected:
                target = int(math.floor(per / px)) if px > 0 else 0
                invested += target * px
                legs.append({**base, "selected": True, "slot_usd": round(per, 2), "target_shares": target,
                             "delta_shares": target - effective_held,
                             "delta_usd": round((target - effective_held) * px, 2)})
            else:
                # not a leader: target 0. If we still HOLD it (confirmed), it must be sold (momentum faded).
                if held > 0:
                    held_off.append(sym)
                legs.append({**base, "selected": False, "target_shares": 0,
                             "delta_shares": -effective_held, "delta_usd": round(-effective_held * px, 2)})
        return {"status": "XSMOM_PLAN", "alloc_usd": round(alloc, 2), "weighting": "equal_weight_top_n",
                "selected": list(selected.keys()), "n_selected": len(selected), "top_n": self.TOP_N,
                "in_flight_ok": inflight["ok"], "deployed_usd": round(invested, 2),
                "held_off_selection": held_off, "legs": legs}

    def _last_rebalance_days(self):
        try:
            d = json.loads(self.STATE.read_text()).get("date")
            return (datetime.utcnow().date() - datetime.fromisoformat(str(d)).date()).days
        except Exception:
            return None

    def _mark_rebalanced(self):
        try:
            self.STATE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE.write_text(json.dumps({"date": datetime.utcnow().date().isoformat()}))
        except Exception:
            pass

    def run_cycle(self, is_regular_session=True, dry_run=False):
        if not self.enabled():
            return {"status": "XSMOM_DISABLED", "acted": False}
        if not is_regular_session:
            return {"status": "XSMOM_MARKET_CLOSED", "acted": False}
        # RECONCILE-FIRST (every cycle, not just rebalance days): sync confirmed held to the live broker
        # BEFORE sizing, so the ledger isn't stale at decision time and trend's share-attribution subtracts
        # xs_momentum's CURRENT holding, not a lagged one. Places no orders.
        try:
            from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
            SleeveTradeLedgerEngine().reconcile_from_broker("xs_momentum", self.UNIVERSE)
        except Exception:
            pass
        p = self.plan()
        # MONTHLY cadence — but ALWAYS act promptly when a held leader has fallen out of the selection
        # (exit a decayed name; don't wait a month). Otherwise only rebalance when due.
        days = self._last_rebalance_days()
        forced_exit = bool(p.get("held_off_selection"))
        due = days is None or days >= self.REBALANCE_DAYS
        if not due and not forced_exit:
            return {"status": "XSMOM_NOT_DUE", "acted": False, "days_since": days,
                    "next_in_days": max(0, self.REBALANCE_DAYS - (days or 0)), "selected": p["selected"]}

        from app.services.sleeve_position_ledger_engine import SleevePositionLedgerEngine
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
        book = TradeStationSimBookingEngine()
        # PER-SLEEVE DEPLOYMENT CAP: this sleeve's own value can't exceed its budget (x buffer) — one sleeve
        # can't eat the book within the total book cap.
        _deployed = sum(max(0, int(lg.get("held") or 0)) * (lg.get("last") or 0) for lg in p["legs"])
        buy_headroom = SleeveCapitalBudgetEngine.deployment_headroom_usd("xs_momentum", _deployed)
        acts, skipped = [], []
        for leg in p["legs"]:
            d = leg.get("delta_shares")
            if not d:
                continue
            # Blind on our own resting orders (degraded read) -> only a real position exit (target 0) may
            # act; a routine buy/trim placed blind is the duplicate that stacks the churn loop.
            if not p.get("in_flight_ok", True) and leg.get("target_shares") != 0:
                skipped.append({"symbol": leg["symbol"], "reason": "orders read degraded — churn guard"})
                continue
            if d > 0 and abs(leg["delta_usd"]) < self.REBALANCE_MIN_USD:
                continue                                  # buys respect the churn floor; sells always act
            action = "BUY" if d > 0 else "SELL"
            qty = abs(d)
            # SELL-CAP: never sell more than THIS sleeve's own broker-confirmed shares (can't touch trend's).
            if action == "SELL" and SleevePositionLedgerEngine.armed():
                own = SleeveTradeLedgerEngine().held_qty("xs_momentum", leg["symbol"])
                qty = min(qty, max(0, own))
                if qty <= 0:
                    skipped.append({"symbol": leg["symbol"], "reason": "sell-cap: no own confirmed shares"})
                    continue
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
            if r.get("ok"):                                  # only log ACCEPTED orders (not cap-rejected)
                try:
                    from app.services.execution_log_engine import ExecutionLogEngine
                    ExecutionLogEngine().record("xs_momentum", leg["symbol"], action, (qty if d > 0 else -qty),
                                                limit, leg["bid"], leg["ask"], r.get("order_id"))
                except Exception:
                    pass
            acts.append({"symbol": leg["symbol"], "action": action, "qty": qty, "limit": limit,
                         "ok": r.get("ok"), "order_id": r.get("order_id")})
        if not dry_run:
            self._mark_rebalanced()
        return {"status": "XSMOM_REBALANCED" if not dry_run else "XSMOM_DRYRUN",
                "acted": bool(acts and not dry_run), "reason": "forced_exit" if (forced_exit and not due) else "due",
                "selected": p["selected"], "actions": acts, "skipped": skipped,
                "in_flight_ok": p.get("in_flight_ok", True), "deployed_usd": p["deployed_usd"]}

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "enabled": self.enabled(),
                "universe": self.UNIVERSE, "construction": "dual_momentum_12_1_cross_sectional",
                "top_n": self.TOP_N, "alloc_usd": round(self._alloc(), 2),
                "days_since_rebalance": self._last_rebalance_days(), "plan": self.plan(),
                "status": "XS_MOMENTUM_STATUS"}
