"""
Mirrors the strategy's decided opens into the TradeStation SIMULATED account as real
paper orders, so the dashboard can reflect broker-simulated fills instead of the
internal ledger's in-process math.

Two hard safety properties:
  * Booking only happens when GREYLINE_SIM_BOOKING_ENABLED=true (default OFF), so this
    is wired and ready but fires nothing until the operator flips it.
  * Every order goes through TradeStationSimBookingEngine, whose fail-closed guard
    refuses anything that is not the sandbox host + a SIM account.

Sizing is whole-share against the $10k mission book (GREYLINE_ACCOUNT_CAPITAL_BASE),
NOT the SIM account's $1M — so observed P&L reflects the intended account size. A name
whose per-position notional is smaller than one share is skipped and reported (the
coarseness of whole-share sizing on a small book, surfaced, never silently dropped).
"""

from datetime import datetime
from os import getenv

from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine

# Opening trade actions in TradeStation v3 terms.
_OPEN_SHORT = {"SELL", "SELL_SHORT", "SELLSHORT", "SHORT"}


class GreyLineSimExecutionEngine:

    def __init__(self):
        self.booking = TradeStationSimBookingEngine()

    @staticmethod
    def enabled():
        return getenv("GREYLINE_SIM_BOOKING_ENABLED", "false").lower() == "true"

    @staticmethod
    def size_shares(notional, price):
        """Whole shares only — TradeStation equity SIM orders are integer quantity."""
        try:
            notional = float(notional); price = float(price)
        except (TypeError, ValueError):
            return 0
        if price <= 0 or notional <= 0:
            return 0
        return int(notional // price)

    @staticmethod
    def _action(side):
        return "SELLSHORT" if str(side).upper() in _OPEN_SHORT else "BUY"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def sim_position(self, symbol):
        """Live (abs quantity, is_long) of a SIM position, or (0, None) if none held.
        SIM is the source of truth for exit sizing — no drift from the fractional book."""
        try:
            rows = (self.booking.positions().get("response_json") or {}).get("Positions") or []
        except Exception:
            return 0.0, None
        for p in rows:
            if str(p.get("Symbol", "")).upper() == str(symbol).upper():
                ls = str(p.get("LongShort", "")).lower()
                return abs(self._f(p.get("Quantity"))), (ls.startswith("long") if ls else None)
        return 0.0, None

    def book_exit(self, symbol, shares, position_long, reason=""):
        """Reduce a SIM position by whole `shares`. LONG -> SELL, SHORT -> BUYTOCOVER."""
        if not self.enabled():
            return {"status": "SIM_BOOKING_DISABLED"}
        shares = int(shares)
        if shares <= 0:
            return {"status": "SKIPPED_ZERO_SHARES", "symbol": symbol, "exit_reason": reason}
        action = "SELL" if position_long else "BUYTOCOVER"
        res = self.booking.place_order(symbol, shares, action=action, order_type="Market", tif="DAY")
        return {"status": "SIM_EXIT_BOOKED", "symbol": symbol, "shares": shares,
                "action": action, "exit_reason": reason, "order_id": res.get("order_id"),
                "ok": res.get("ok")}

    def close_position(self, symbol, position_long=None, reason=""):
        """Flatten the entire live SIM position for a symbol (exact — the stop/close path)."""
        if not self.enabled():
            return {"status": "SIM_BOOKING_DISABLED"}
        qty, is_long = self.sim_position(symbol)
        if qty <= 0:
            return {"status": "NO_SIM_POSITION", "symbol": symbol}
        long_ = is_long if position_long is None else position_long
        return self.book_exit(symbol, qty, bool(long_), reason=reason)

    def book_opens(self, opens, per_name_notional):
        """opens: list of {symbol, side, entry_price}. Places one SIM market order per
        name, sized to per_name_notional in whole shares. No-op unless enabled."""
        if not self.enabled():
            return {"timestamp": datetime.utcnow().isoformat(),
                    "status": "SIM_BOOKING_DISABLED", "placed": 0, "booked": []}

        booked = []
        for o in opens:
            symbol = o.get("symbol")
            shares = self.size_shares(per_name_notional, o.get("entry_price"))
            if shares <= 0:
                booked.append({"symbol": symbol, "status": "SKIPPED_SUB_SHARE_NOTIONAL",
                               "shares": 0})
                continue
            action = self._action(o.get("side"))
            # Validated entry for momentum is MARKET (limit-pullback adversely selects);
            # DAY so it works at the open and never rests overnight unintentionally.
            res = self.booking.place_order(symbol, shares, action=action,
                                           order_type="Market", tif="DAY")
            booked.append({"symbol": symbol, "shares": shares, "action": action,
                           "order_id": res.get("order_id"), "http_status": res.get("http_status"),
                           "ok": res.get("ok")})
        return {"timestamp": datetime.utcnow().isoformat(), "status": "SIM_BOOKED",
                "placed": sum(1 for b in booked if b.get("ok")),
                "skipped_sub_share": sum(1 for b in booked if b.get("shares") == 0),
                "booked": booked}
