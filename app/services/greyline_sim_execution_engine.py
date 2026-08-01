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

    def _option_quote(self, option_symbol):
        """Live (bid, ask, source) for an option contract. TradeStation is primary (real-time,
        already paid for); UW is the SECOND source, used only when TS is missing/one-sided — so a
        data hiccup never forces an urgent exit to market or skips a patient one. UW agrees with
        TS to the penny on held names, and the fallback only spends UW budget when TS fails."""
        bid = ask = 0.0
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            q = TradeStationQuoteLiveEngine().get_quote(option_symbol)
            rj = q.get("response_json") or {}
            row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
            bid, ask = self._f(row.get("Bid")), self._f(row.get("Ask"))
        except Exception:
            bid = ask = 0.0
        if bid > 0 and ask > 0 and ask >= bid:
            return bid, ask, "tradestation"
        # TS unusable — try UW's NBBO for the same contract before giving up.
        try:
            from app.services.uw_option_quote_engine import UWOptionQuoteEngine
            uw = UWOptionQuoteEngine()
            if uw.enabled():
                ubid, uask = uw.quote(option_symbol)
                if ubid > 0 and uask > 0 and uask >= ubid:
                    return ubid, uask, "unusual_whales"
        except Exception:
            pass
        return bid, ask, "tradestation"   # whatever TS gave (possibly 0/one-sided) — policy handles it

    _WORKING = ("received", "open", "queued", "sent", "partiallyfilled")

    def _working_close_orders(self, option_symbol):
        """Working SELLTOCLOSE orders resting on this contract — so we neither stack duplicate
        limits nor leave a passive take-profit resting when an urgent stop must fire."""
        try:
            orders = (self.booking.orders().get("response_json") or {}).get("Orders") or []
        except Exception:
            return []
        out = []
        for o in orders:
            if str(o.get("StatusDescription", "")).lower() not in self._WORKING:
                continue
            leg = (o.get("Legs") or [{}])[0]
            if str(leg.get("Symbol", "")).upper() != str(option_symbol).upper():
                continue
            if str(leg.get("BuyOrSell", "")).lower().startswith("sell"):
                out.append(o)
        return out

    def book_exit(self, symbol, shares, position_long, reason=""):
        """Reduce a SIM position by whole `shares`. LONG -> SELL, SHORT -> BUYTOCOVER."""
        if not self.enabled():
            return {"status": "SIM_BOOKING_DISABLED"}
        shares = int(shares)
        if shares <= 0:
            return {"status": "SKIPPED_ZERO_SHARES", "symbol": symbol, "exit_reason": reason}
        action = "SELL" if position_long else "BUYTOCOVER"
        # A SELL is rejected ("long N with N remaining on sell orders") while a broker protective
        # StopMarket reserves the shares — clear it first, exactly as the trend/carry/flatten exit
        # paths do. Without this, momentum doctrine exits (ATR stop + TP scale-outs) silently fail
        # to reduce the position. The stop engine re-arms on the remaining shares next cycle. Only
        # a long SELL collides with a resting sell-stop; BUYTOCOVER (short) does not.
        if action == "SELL":
            try:
                from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
                BrokerProtectiveStopEngine().clear_stop(symbol)
            except Exception:
                pass
        res = self.booking.place_order(symbol, shares, action=action, order_type="Market", tif="DAY")
        return {"status": "SIM_EXIT_BOOKED", "symbol": symbol, "shares": shares,
                "action": action, "exit_reason": reason, "order_id": res.get("order_id"),
                "ok": res.get("ok")}

    def close_position(self, symbol, position_long=None, reason="", already_booked=0):
        """Flatten the entire live SIM position for a symbol (exact — the stop/close path).

        `already_booked` nets out exit shares booked earlier in the same pass but not yet
        reflected in the live position. A gap can cross several TPs and the stop in one
        decide(), so the scale-outs are still in flight when this reads positions() —
        flattening the unreduced quantity would sell more than is held and flip the
        account short.
        """
        if not self.enabled():
            return {"status": "SIM_BOOKING_DISABLED"}
        qty, is_long = self.sim_position(symbol)
        qty = qty - max(0, int(already_booked or 0))
        if qty <= 0:
            return {"status": "NO_SIM_POSITION", "symbol": symbol}
        long_ = is_long if position_long is None else position_long
        return self.book_exit(symbol, qty, bool(long_), reason=reason)

    def book_opens(self, opens, per_name_notional):
        """opens: list of {symbol, side, entry_price, quantity?}. Places one SIM market order
        per name. Books the caller's RECORDED whole-share `quantity` when present, so the SIM
        books EXACTLY what the ledger recorded — no dual-path divergence when the caller sizes
        names unequally (e.g. budget-float sizing). Falls back to sizing at per_name_notional
        only when no quantity is supplied. No-op unless enabled."""
        if not self.enabled():
            return {"timestamp": datetime.utcnow().isoformat(),
                    "status": "SIM_BOOKING_DISABLED", "placed": 0, "booked": []}

        booked = []
        for o in opens:
            symbol = o.get("symbol")
            try:
                rec_qty = int(o.get("quantity")) if o.get("quantity") is not None else 0
            except (TypeError, ValueError):
                rec_qty = 0
            shares = rec_qty if rec_qty > 0 else self.size_shares(per_name_notional, o.get("entry_price"))
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

    def book_option_opens(self, options):
        """options: list of {option_symbol, contracts, limit_price?}. Places one BUYTOOPEN DAY
        order per contract set. If `limit_price` is given it's a LIMIT order (waits to fill at
        that price — the Phase-2 forecasted entry); otherwise MARKET (fills immediately). Both
        BUY-to-open a call (bullish) or put (bearish) — the directional view is already baked
        into the chosen contract. No-op unless GREYLINE_SIM_BOOKING_ENABLED=true."""
        if not self.enabled():
            return {"timestamp": datetime.utcnow().isoformat(),
                    "status": "SIM_BOOKING_DISABLED", "placed": 0, "booked": []}

        booked = []
        for o in options:
            sym = o.get("option_symbol")
            qty = int(o.get("contracts") or 0)
            if not sym or qty <= 0:
                booked.append({"option_symbol": sym, "status": "SKIPPED_NO_SYMBOL_OR_QTY",
                               "contracts": qty})
                continue
            limit = o.get("limit_price")
            if limit and float(limit) > 0:
                res = self.booking.place_order(sym, qty, action="BUYTOOPEN",
                                               order_type="Limit", limit_price=round(float(limit), 2),
                                               tif="DAY")
                order_type = "Limit"
            else:
                res = self.booking.place_order(sym, qty, action="BUYTOOPEN",
                                               order_type="Market", tif="DAY")
                order_type = "Market"
            booked.append({"option_symbol": sym, "contracts": qty, "action": "BUYTOOPEN",
                           "order_type": order_type, "limit_price": round(float(limit), 2) if limit else None,
                           "order_id": res.get("order_id"), "http_status": res.get("http_status"),
                           "ok": res.get("ok")})
        return {"timestamp": datetime.utcnow().isoformat(), "status": "SIM_OPTIONS_BOOKED",
                "placed": sum(1 for b in booked if b.get("ok")), "booked": booked}

    def book_option_close(self, option_symbol, contracts=0, reason=""):
        """SELLTOCLOSE an option position in SIM — FULL or PARTIAL.

        `contracts`: how many to close. 0/None (or a value >= the live position) closes the
        WHOLE position; a smaller positive value closes exactly that many (one exit tranche of
        a 4-TP ladder). Either way the quantity is CAPPED at the live broker position — the
        broker is the source of truth, so we never sell-to-close more than is held (which would
        open a naked short). No-op if flat or booking disabled. This is what makes an option
        exit real: a laddered close in the doctrine also happens at the broker.
        """
        if not self.enabled():
            return {"status": "SIM_BOOKING_DISABLED"}
        if not option_symbol:
            return {"status": "SKIPPED_NO_OPTION_SYMBOL"}
        live_qty, _ = self.sim_position(option_symbol)
        live = int(live_qty) if live_qty and live_qty > 0 else 0
        if live <= 0:
            return {"status": "NO_SIM_OPTION_POSITION", "option_symbol": option_symbol}
        want = int(contracts) if contracts and int(contracts) > 0 else live
        qty = min(want, live)   # never oversell into a short
        if qty <= 0:
            return {"status": "NO_SIM_OPTION_POSITION", "option_symbol": option_symbol}

        # Price the exit instead of dumping it at market. Urgency comes from the exit reason:
        # a stop/maturity liquidation is a marketable limit at the bid (fills now, floored); a
        # take-profit tranche is a patient limit near the ask (captures spread, may wait).
        from app.services.options_exit_execution_engine import OptionsExitExecutionEngine
        policy = OptionsExitExecutionEngine()
        urgency = policy.classify(reason)
        bid, ask, quote_source = self._option_quote(option_symbol)
        plan = policy.price_exit(bid, ask, reason, urgency=urgency)

        # Do not leave stale/duplicate resting closes. If a working close already rests: a PATIENT
        # tranche should not stack another (skip); an URGENT exit must win, so cancel it first and
        # replace with the marketable order — a stop can never be blocked by a resting limit.
        working = self._working_close_orders(option_symbol)
        cancelled = []
        if working:
            if urgency == "urgent":
                for o in working:
                    c = self.booking.cancel_order(o.get("OrderID"))
                    if c.get("ok"):
                        cancelled.append(o.get("OrderID"))
            else:
                return {"status": "SKIPPED_WORKING_CLOSE_EXISTS", "option_symbol": option_symbol,
                        "contracts": qty, "exit_reason": reason, "urgency": urgency,
                        "detail": "a take-profit limit is already resting on this contract"}

        if plan.get("skip"):
            return {"status": "SKIPPED_NO_QUOTE_PATIENT", "option_symbol": option_symbol,
                    "contracts": qty, "exit_reason": reason, "urgency": urgency,
                    "detail": plan.get("rationale")}

        # Clear any resting protective stop on this contract before the SELLTOCLOSE, so it isn't
        # rejected for reserved contracts (no-op when none is armed — e.g. VRP legs carry none).
        try:
            from app.services.broker_protective_stop_engine import BrokerProtectiveStopEngine
            BrokerProtectiveStopEngine().clear_stop(option_symbol)
        except Exception:
            pass
        res = self.booking.place_order(
            option_symbol, qty, action="SELLTOCLOSE",
            order_type=plan["order_type"],
            limit_price=plan.get("limit_price") if plan["order_type"] == "Limit" else None,
            tif="DAY")

        # Record the decision context so the exit reconciler can later measure realized price vs
        # mid and vs the naked-market counterfactual (the bid). Best-effort — never break the close.
        if res.get("ok") and res.get("order_id"):
            try:
                from app.services.options_exit_reconciler_engine import OptionsExitReconcilerEngine
                OptionsExitReconcilerEngine().record_pending({
                    "order_id": res.get("order_id"), "option_symbol": option_symbol,
                    "contracts": qty, "reason": reason, "urgency": urgency,
                    "order_type": plan["order_type"], "limit_price": plan.get("limit_price"),
                    "decision_mid": plan.get("mid"), "decision_bid": round(bid, 2) if bid else None,
                    "decision_ask": round(ask, 2) if ask else None, "quote_source": quote_source,
                    "forced_market": plan.get("forced_market", False)})
            except Exception:
                pass

        return {"status": "SIM_OPTION_CLOSE_BOOKED", "option_symbol": option_symbol,
                "contracts": qty, "live_before": live, "partial": qty < live,
                "action": "SELLTOCLOSE", "exit_reason": reason,
                "urgency": urgency, "order_type": plan["order_type"],
                "limit_price": plan.get("limit_price"), "exit_mid": plan.get("mid"),
                "quote_source": quote_source,
                "forced_market": plan.get("forced_market", False),
                "cancelled_working": cancelled, "pricing_rationale": plan.get("rationale"),
                "order_id": res.get("order_id"), "http_status": res.get("http_status"),
                "ok": res.get("ok")}
