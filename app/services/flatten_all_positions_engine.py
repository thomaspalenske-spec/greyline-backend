"""Flatten the ENTIRE book to zero — a clean-slate reset tool, not a strategy.

When the operator wants GreyLine back to a known baseline (0 positions held), this closes every open
leg the broker reports, sized from the LIVE broker quantity (never a ledger count — a ledger-sized
close is how you end up naked short). It handles both sides:

    long option  (qty > 0)  -> SELLTOCLOSE at the bid   (marketable)
    short option (qty < 0)  -> BUYTOCLOSE  at the ask   (marketable)
    long stock   (qty > 0)  -> SELL        near the bid
    short stock  (qty < 0)  -> BUYTOCOVER  near the ask

CRITICAL ORDERING: shorts are closed BEFORE longs. In a spread, buying back the short leg first
removes the naked-risk; if we sold the long first and the short did not fill, we would be momentarily
naked short. So every buy-to-close/cover is placed before any sell-to-close in the same cycle.

Only runs during the regular session (options do not fill after hours). One working close per symbol
(skip if one already rests) so a re-run never double-sends. Self-terminating: 0 held -> FLAT no-op.
Gated by GREYLINE_FLATTEN_ALL_ENABLED so it can never fire unless the operator explicitly arms it.
"""

import re
from datetime import datetime
from os import getenv


class FlattenAllPositionsEngine:

    _OPT = re.compile(r"^([A-Z.]+)\s+\d{6}[CP]\d")     # "IWM 260904C311" -> option
    _ACTIVE = {"Queued", "Received", "Open", "Sending", "Partially Filled", "Accepted"}

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_FLATTEN_ALL_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _is_option(cls, symbol):
        return bool(cls._OPT.match(str(symbol or "").upper().strip()))

    # ---- live broker state (the only source of truth for size) ---------------------------------

    def _positions(self, book):
        """[(symbol, qty)] for EVERY non-zero position the broker reports (both signs)."""
        rj = (book.positions().get("response_json") or {})
        out = []
        for p in (rj.get("Positions") or []):
            q = int(self._f(p.get("Quantity")))
            if q != 0:
                out.append((p.get("Symbol"), q))
        return out

    REPRICE_TOL = 0.01     # keep a resting close if within 1% of the current marketable touch

    def _working_closes(self, book, symbol):
        """[(order_id, limit_price)] of live working orders resting on this symbol."""
        rj = (book.orders().get("response_json") or {})
        out = []
        for o in (rj.get("Orders") or []):
            if o.get("StatusDescription") not in self._ACTIVE:
                continue
            if (o.get("Legs") or [{}])[0].get("Symbol") == symbol:
                out.append((o.get("OrderID"), self._f(o.get("LimitPrice"))))
        return out

    # ---- close ticket for one leg --------------------------------------------------------------

    def _close_ticket(self, symbol, qty, bid, ask):
        """(action, order_type, limit) to flatten this leg with a marketable limit, or None."""
        opt = self._is_option(symbol)
        if qty > 0:                                   # long -> sell to close, hit the bid
            action = "SELLTOCLOSE" if opt else "SELL"
            price = bid
        else:                                         # short -> buy to close, pay the ask
            action = "BUYTOCLOSE" if opt else "BUYTOCOVER"
            price = ask if ask > 0 else bid
        if price <= 0:
            return None
        if opt:
            from app.services.options_entry_forecast_engine import OptionsEntryForecastEngine
            tick = OptionsEntryForecastEngine._tick_for(bid, ask) or 0.05
            price = round(round(price / tick) * tick, 2)
        else:
            price = round(price, 2)
        if price <= 0:
            return None
        return action, "Limit", price

    # ---- main cycle ----------------------------------------------------------------------------

    def run_cycle(self, is_regular_session=True, dry_run=False, only_symbols=None):
        # TARGETED mode: only_symbols flattens ONLY those tickers (e.g. orphaned positions from a disarmed
        # sleeve), leaving every other position untouched. The caller owns the gate in targeted mode (the
        # scheduler checks GREYLINE_ORPHAN_FLATTEN); the GREYLINE_FLATTEN_ALL_ENABLED arm is for whole-book.
        if only_symbols is None and not self.enabled():
            return {"status": "FLATTEN_ALL_DISABLED", "held": 0, "actions": []}
        if not is_regular_session:
            return {"status": "FLATTEN_ALL_MARKET_CLOSED", "held": 0, "actions": [],
                    "note": "options do not fill after hours; flatten runs at the next regular session"}

        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        book = TradeStationSimBookingEngine()
        quotes = TradeStationQuoteLiveEngine()

        held = self._positions(book)
        if only_symbols is not None:
            allow = {str(s).upper().strip() for s in only_symbols}
            held = [(sym, qty) for (sym, qty) in held if str(sym).upper().strip() in allow]
        if not held:
            return {"status": "FLATTEN_ALL_FLAT", "held": 0, "actions": [],
                    "note": ("targeted symbols already flat" if only_symbols is not None
                             else "no positions held — book is flat")}

        # shorts first (buy-to-close removes naked-risk), then longs
        held.sort(key=lambda sq: 0 if sq[1] < 0 else 1)

        actions = []
        for symbol, qty in held:
            try:
                rj = (quotes.get_quote(symbol).get("response_json") or {})
                row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
                bid, ask = self._f(row.get("Bid")), self._f(row.get("Ask"))
                ticket = self._close_ticket(symbol, qty, bid, ask)
                if ticket is None:
                    actions.append({"symbol": symbol, "qty": qty, "skipped": "no usable price"})
                    continue
                action, otype, limit = ticket
                if dry_run:
                    actions.append({"symbol": symbol, "qty": qty, "would": action, "limit": limit,
                                    "bid": bid, "ask": ask})
                    continue

                # keep a resting close only if it is still at the marketable touch — else it can sit
                # unfilled on a thin strike and never flatten. Otherwise cancel-CONFIRM-replace so a
                # re-price can never leave two live orders racing.
                existing = self._working_closes(book, symbol)
                if len(existing) == 1 and existing[0][1] > 0 and \
                        abs(existing[0][1] - limit) <= self.REPRICE_TOL * limit:
                    actions.append({"symbol": symbol, "qty": qty, "action": "resting — kept",
                                    "limit": existing[0][1]})
                    continue
                for oid, _ in existing:
                    book.cancel_order(oid)
                if self._working_closes(book, symbol):
                    actions.append({"symbol": symbol, "qty": qty,
                                    "skipped": "cancel not confirmed — retry next cycle"})
                    continue
                # selling a LONG is rejected while a broker protective stop reserves the shares
                # ("long N with N on sell orders"). Clear it first so the emergency flatten can fire.
                if action in ("SELL", "SELLTOCLOSE"):
                    try:
                        from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                        BrokerProtectiveStopEngine().clear_stop(symbol)
                    except Exception:
                        pass
                r = book.place_order(symbol, abs(qty), action=action, order_type=otype,
                                     limit_price=limit, tif="DAY")
                actions.append({"symbol": symbol, "qty": qty, "action": action, "limit": limit,
                                "ok": r.get("ok"), "order_id": r.get("order_id")})
            except Exception as exc:
                actions.append({"symbol": symbol, "qty": qty, "error": repr(exc)[:120]})

        return {"status": "FLATTEN_ALL_WORKING", "held": len(held), "actions": actions,
                "timestamp": datetime.utcnow().isoformat()}
