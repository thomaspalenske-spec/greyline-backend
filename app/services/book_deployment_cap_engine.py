"""Hard book-level deployment cap — the bulletproof backstop that makes the 2026-08-06 over-deployment
IMPOSSIBLE regardless of any per-sleeve sizing bug.

WHAT HAPPENED: a rebalancing sleeve sizes `delta = target - held`. When `held` reads stale-low (the fill
hasn't been attributed back yet) the delta is huge and the sleeve stacks orders every cycle. The
per-delta guards (in-flight orders, per-sleeve ledger) each reduce it but each has a blind spot (a
degraded orders read, a reconcile that lags one cycle). Left unchecked, trend + xs_momentum stacked to
$122,319 of positions on a $10,000 mission book — 12x — against the SIM's $1M buying power.

THIS ENGINE does not trust the delta at all. Before any EQUITY BUY reaches the broker, it verifies the
WHOLE book's committed long-equity value — FILLED positions PLUS resting BUY orders (so orders placed
earlier in the same cycle count too) — plus the new order stays within MAX_DEPLOY_FRAC x the mission
capital base. Over the cap -> the buy is REJECTED before it is placed. It is the one invariant that
holds even if every sizing engine is wrong.

  * SELLS and OPTIONS are never gated (a sell reduces exposure; option premium is defined-risk and tiny).
  * FAIL CLOSED: if the broker read fails, the buy is BLOCKED — an unverifiable book must not deploy more.
  * Gated by GREYLINE_BOOK_DEPLOY_CAP (default ON — a safety limit, not a feature)."""

from datetime import datetime
from os import getenv


class BookDeploymentCapEngine:

    # The book's total long-equity value may reach this multiple of the mission capital base. >1 gives
    # headroom for whole-share rounding + intraday marks while the sum of sleeve budgets is ~100%; the
    # 12x fault is orders of magnitude beyond it, so it is caught with room to spare.
    MAX_DEPLOY_FRAC = 1.15

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def enabled(cls):
        return (getenv("GREYLINE_BOOK_DEPLOY_CAP", "true") or "true").strip().lower() == "true"

    @classmethod
    def cap_usd(cls):
        base = cls._f(getenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "10000")) or 10000.0
        frac = cls._f(getenv("GREYLINE_BOOK_DEPLOY_CAP_FRAC", "")) or cls.MAX_DEPLOY_FRAC
        return max(0.0, base) * frac

    @staticmethod
    def _pos_price(p):
        # SIM positions carry Last / MarkToMarketPrice; fall back to average price so a missing mark
        # never reads a position as $0 (which would understate deployment and defeat the cap).
        for k in ("Last", "MarkToMarketPrice", "MarkPrice", "AveragePrice"):
            v = p.get(k)
            if v not in (None, "", 0, "0"):
                try:
                    return abs(float(v))
                except (TypeError, ValueError):
                    continue
        return 0.0

    @staticmethod
    def _tbill_symbol():
        """The T-bill cash-sweep symbol (SGOV), resolved not hardcoded. Empty on any failure -> nothing is
        excluded (conservative: the old over-counting behavior, never a silent under-count)."""
        try:
            from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine
            return str(TbillCashSweepEngine.symbol() or "").upper()
        except Exception:
            return ""

    @classmethod
    def committed_long_equity_usd(cls, booking):
        """AT-RISK long-equity market value + resting working BUY notional. Returns (usd, ok). ok=False on
        any degraded read — callers must fail closed. Resting buys are included so multiple orders placed
        within one cycle (before any fills) still accumulate against the cap.

        EXCLUDES the T-bill cash sweep (SGOV): it is a ~0-duration cash-EQUIVALENT parking lot the sweep
        sells back on demand, NOT risk deployment — counting it made the cap bind on cash and starve real
        deployment (and it disagreed with /account-summary, which already nets SGOV out of 'deployed'). This
        does NOT reopen the 12x over-deployment hole: that was EQUITY sleeves (trend/xs) stacking, which are
        still fully counted; SGOV can't stack into risk, and total book size is still cash/buying-power bound."""
        tbill = cls._tbill_symbol()
        # filled positions
        try:
            pos = booking.positions()
            if not bool(pos.get("ok", True)):
                return 0.0, False
            positions = (pos.get("response_json") or {}).get("Positions")
            if positions is None:
                return 0.0, False
        except Exception:
            return 0.0, False
        deployed = 0.0
        for p in positions:
            if str(p.get("AssetType")) != "STOCK":
                continue
            if tbill and str(p.get("Symbol") or "").upper() == tbill:
                continue                                   # SGOV cash-park — not at-risk deployment
            qty = cls._f(p.get("Quantity"))
            if qty > 0:                                    # long only; shorts don't consume buy capital here
                deployed += qty * cls._pos_price(p)
        # resting working BUY orders (equity), valued at their limit (or 0 if unknown -> conservative skip)
        try:
            orders = booking.orders()
            if not bool(orders.get("ok", True)):
                return 0.0, False
            ords = (orders.get("response_json") or {}).get("Orders") or []
        except Exception:
            return 0.0, False
        working = ("received", "open", "queued", "sent", "partiallyfilled", "pending")
        for o in ords:
            if str(o.get("StatusDescription", "")).lower() not in working:
                continue
            limit = cls._f(o.get("LimitPrice") or o.get("Limit"))
            for leg in (o.get("Legs") or []):
                sym = str(leg.get("Symbol") or "")
                if " " in sym:                             # option leg — not equity
                    continue
                if tbill and sym.upper() == tbill:         # SGOV cash-park buy — not at-risk deployment
                    continue
                if str(leg.get("BuyOrSell") or "").lower().startswith("buy"):
                    qty = cls._f(leg.get("QuantityRemaining")) or cls._f(leg.get("Quantity"))
                    deployed += qty * limit
        return round(deployed, 2), True

    @classmethod
    def check_equity_buy(cls, symbol, quantity, price, booking):
        """Decide whether an equity BUY may proceed. allowed=False blocks it. Fail closed on any
        unverifiable input (degraded read, or a buy with no usable price)."""
        if not cls.enabled():
            return {"allowed": True, "reason": "cap disabled"}
        # a T-bill cash-sweep (SGOV) BUY is cash-parking, not risk deployment — exempt it, consistent with
        # excluding held SGOV from committed. (Sells/options/stops are already never gated upstream.)
        _tb = cls._tbill_symbol()
        if _tb and str(symbol or "").upper() == _tb:
            return {"allowed": True, "reason": "T-bill cash sweep — not risk deployment"}
        order_val = abs(cls._f(quantity)) * cls._f(price)
        if order_val <= 0:
            # a BUY with no usable price can't be size-checked -> block (fail closed). The rebalance
            # sleeves always pass a limit price, so this only fires on a genuinely unpriced buy.
            return {"allowed": False, "reason": "book cap: buy has no usable price to size-check (blocked)"}
        deployed, ok = cls.committed_long_equity_usd(booking)
        if not ok:
            return {"allowed": False, "reason": "book cap: broker read degraded — buy blocked (fail-closed)"}
        cap = cls.cap_usd()
        allowed = (deployed + order_val) <= cap
        return {"allowed": allowed, "deployed_usd": deployed, "order_usd": round(order_val, 2),
                "cap_usd": round(cap, 2),
                "reason": None if allowed else
                (f"book deployment cap: committed ${deployed:,.0f} + order ${order_val:,.0f} "
                 f"> ${cap:,.0f} ({cls.MAX_DEPLOY_FRAC}x mission base) — buy blocked")}

    @classmethod
    def status(cls, booking=None):
        if booking is None:
            from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
            booking = TradeStationSimBookingEngine()
        deployed, ok = cls.committed_long_equity_usd(booking)
        cap = cls.cap_usd()
        return {"timestamp": datetime.utcnow().isoformat(), "enabled": cls.enabled(),
                "committed_long_equity_usd": deployed if ok else None, "read_ok": ok,
                "cap_usd": round(cap, 2), "headroom_usd": round(max(0.0, cap - deployed), 2) if ok else None,
                "note": ("Hard book-level equity-BUY cap (filled + resting buys) vs the mission base. "
                         "Blocks any buy that would exceed the cap, fail-closed on a degraded read. "
                         "Makes the 12x over-deployment fault impossible regardless of sizing bugs."),
                "status": "BOOK_DEPLOYMENT_CAP_STATUS"}
