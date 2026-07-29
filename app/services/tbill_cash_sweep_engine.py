"""Sweep idle mission cash into a T-bill ETF so it earns instead of sitting dead.

The account lost 41% actively trading with no proven edge, while its idle cash earned nothing. The
single highest-confidence improvement is to hold that idle capital in a ~0-duration Treasury ETF
(SGOV / BIL, ~4.5% yield, near-zero volatility) — a guaranteed-positive baseline that already beats
the tiny condor book's expected value. This engine holds `mission_equity - RESERVE` in the T-bill
proxy, keeping RESERVE liquid so the premium strategies can still open, and rebalances only when the
gap is material (no churn).

HONEST CAVEAT: in a LIVE account SGOV pays monthly distributions (the yield). In the PAPER SIM it is
UNCERTAIN whether TradeStation credits those distributions — so the yield may not visibly accrue in
the test. The engine is still correct (it's the right live behavior, and holding SGOV never hurts —
it's the safest asset), but it will NOT fabricate income the account didn't actually receive.
"""

import math
from datetime import datetime
from os import getenv


class TbillCashSweepEngine:

    DEFAULT_SYMBOL = "SGOV"          # iShares 0-3 Month Treasury; ~$100.5, monthly distributions
    DEFAULT_RESERVE_USD = 2500.0     # keep this much liquid for the premium strategies (caps ~$2.1k)
    MIN_REBALANCE_USD = 200.0        # don't churn for small deltas

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_TBILL_SWEEP_ENABLED", "") or "").strip().lower() == "true"

    @classmethod
    def symbol(cls):
        return (getenv("GREYLINE_TBILL_SYMBOL", "") or cls.DEFAULT_SYMBOL).strip().upper()

    @classmethod
    def _reserve(cls):
        try:
            return float(getenv("GREYLINE_TBILL_RESERVE_USD", "") or cls.DEFAULT_RESERVE_USD)
        except (TypeError, ValueError):
            return cls.DEFAULT_RESERVE_USD

    # ---- inputs -------------------------------------------------------------------------------

    def _mission_equity(self):
        """base + cumulative realized + live unrealized — the same figure the dashboard shows."""
        try:
            base = float(getenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "10000") or 10000)
        except (TypeError, ValueError):
            base = 10000.0
        try:
            from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine
            realized = MissionRealizedPnlEngine().cumulative_realized()
        except Exception:
            realized = 0.0
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            rows = BrokerAccountViewEngine().snapshot().get("positions", []) or []
            unrealized = sum(self._f(r.get("unrealized_pnl")) for r in rows)
        except Exception:
            unrealized = 0.0
        return round(base + realized + unrealized, 2)

    def _held_shares(self):
        try:
            from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
            sym = self.symbol()
            for x in ((TradeStationPositionsLiveEngine().get_positions().get("response_json") or {})
                      .get("Positions") or []):
                if str(x.get("Symbol") or "").upper() == sym and x.get("AssetType") == "STOCK":
                    return int(self._f(x.get("Quantity")))
        except Exception:
            pass
        return 0

    def _quote(self):
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            rj = (TradeStationQuoteLiveEngine().get_quote(self.symbol()).get("response_json") or {})
            row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
            return self._f(row.get("Bid")), self._f(row.get("Ask")), self._f(row.get("Last") or row.get("Close"))
        except Exception:
            return 0.0, 0.0, 0.0

    # ---- sweep --------------------------------------------------------------------------------

    def plan(self):
        sym = self.symbol()
        equity = self._mission_equity()
        held = self._held_shares()
        bid, ask, last = self._quote()
        px = last or ask or bid
        if px <= 0:
            return {"status": "NO_QUOTE", "symbol": sym}
        reserve = self._reserve()
        target_value = max(0.0, equity - reserve)
        target_shares = int(math.floor(target_value / px))
        delta = target_shares - held
        return {
            "symbol": sym, "mission_equity": equity, "reserve_usd": reserve,
            "price": px, "held_shares": held, "held_value": round(held * px, 2),
            "target_value": round(target_value, 2), "target_shares": target_shares,
            "delta_shares": delta, "delta_value": round(delta * px, 2), "bid": bid, "ask": ask,
        }

    def sweep(self, dry_run=True):
        if not self.enabled():
            return {"status": "TBILL_SWEEP_DISABLED", "acted": False}
        p = self.plan()
        if p.get("status") == "NO_QUOTE":
            return {**p, "acted": False}
        delta = p["delta_shares"]
        if abs(p["delta_value"]) < self.MIN_REBALANCE_USD or delta == 0:
            return {**p, "status": "TBILL_IN_BALANCE", "acted": False}
        if dry_run:
            return {**p, "status": "TBILL_SWEEP_DRYRUN", "acted": False,
                    "would": ("BUY" if delta > 0 else "SELL", abs(delta), p["symbol"])}
        # marketable limit (SGOV is penny-tight): buy at ask, sell at bid
        action = "BUY" if delta > 0 else "SELL"
        limit = round(p["ask"] if delta > 0 else p["bid"], 2)
        # a SELL is rejected while a protective stop reserves the shares — clear it first.
        if action == "SELL":
            try:
                from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                BrokerProtectiveStopEngine().clear_stop(p["symbol"])
            except Exception:
                pass
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        r = TradeStationSimBookingEngine().place_order(p["symbol"], abs(delta), action=action,
                                                       order_type="Limit", limit_price=limit, tif="DAY")
        try:
            from app.services.execution_log_engine import ExecutionLogEngine
            ExecutionLogEngine().record("tbill", p["symbol"], action, delta, limit,
                                        p["bid"], p["ask"], r.get("order_id"))
        except Exception:
            pass
        return {**p, "status": "TBILL_SWEEP_ORDERED", "acted": True,
                "action": action, "qty": abs(delta), "limit": limit,
                "ok": r.get("ok"), "order_id": r.get("order_id"),
                "note": "idle mission cash parked in T-bills; earns yield in a live account "
                        "(paper-sim distribution crediting is uncertain — not fabricated)"}

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "armed": self.enabled(), **self.plan(),
                "status": "TBILL_CASH_SWEEP_STATUS"}
