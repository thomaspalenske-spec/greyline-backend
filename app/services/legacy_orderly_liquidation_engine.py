"""Optimally liquidate the legacy pre-clean-test book — best price first, guaranteed exit second.

Before the Variance-Premium OS takes over (2026-07-26), eight legacy positions must leave the
book: four single-name calls (ALAB/GLW/MRNA/RKLB, wide OTM, 18-38% spreads) and four small
equities (ALTO/CIEN/GLW/MRNA). A resting limit placed on the weekend is priced off STALE weekend
quotes and never re-prices itself — so it either dumps at the bid (giving up half a fat spread) or
sits above the ask and never fills. Neither is acceptable when the whole point is a clean, fully
flat book at Monday's open.

This engine runs each scheduler cycle DURING the regular session and drives those exits against
LIVE quotes, on a price-first / exit-guaranteed ladder:

  OPTIONS  (spread is real money):
    * first ~10 min  — PATIENT: rest near the ask (OptionsExitExecutionEngine) to CAPTURE spread.
    * ~10-25 min     — MID: meet the market halfway if the patient post has not filled.
    * after ~25 min  — URGENT: a MARKETABLE LIMIT at the bid — fills immediately against resting
                       bid liquidity, with the bid as a hard floor. The position WILL be flat.

  EQUITIES (spread is pennies; the open cross is already fair):
    * a marketable limit a hair below the live bid — fills at the opening print. Re-read each
      cycle so a gap-down is chased down and still flattens fast.

Safety, non-negotiable:
  * size EVERY close from the LIVE broker position quantity — never a ledger count (a ledger-sized
    close is how you end up naked short).
  * one working close per symbol: cancel-and-CONFIRM-gone before placing a replacement, so a
    re-price can never leave two live sells racing into a double-sell.
  * options sell as SELLTOCLOSE with the full OCC-style symbol; equities sell as SELL on the ticker.
  * scoped to an explicit legacy target set and SELF-TERMINATING: once a symbol is no longer held
    it is dropped, and when the set is empty the engine is a no-op forever. It never touches a
    VRP-OS position.
"""

import json
import re
from datetime import datetime
from os import getenv
from pathlib import Path


class LegacyOrderlyLiquidationEngine:

    # The explicit legacy book to flatten. Anything not in this set is ignored — the VRP OS's own
    # positions are never eligible. Symbols are matched against the live broker position symbols.
    TARGETS = {
        "ALAB 260828C315", "GLW 260828C180", "MRNA 260828C60", "RKLB 260828C70",  # legacy calls
        "ALTO", "CIEN", "GLW", "MRNA",                                            # legacy equities
    }

    SESSION_MARKER = Path("app/data/legacy_liquidation_session.json")

    # option escalation ladder, minutes since the session opened
    PATIENT_UNTIL_MIN = 10      # < this: rest near the ask, capture spread
    MID_UNTIL_MIN = 25          # < this: meet at the mid; >= this: marketable at the bid (guaranteed)

    EQUITY_MARKETABLE_FRAC = 0.98   # equity sell limit = live_bid * this (marketable, inside the band)
    REPRICE_TOL = 0.01              # leave an existing close alone if within 1% of the desired price

    _OPT = re.compile(r"^([A-Z.]+)\s+\d{6}[CP]\d")   # "ALAB 260828C315" -> option

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_LEGACY_LIQUIDATION_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _is_option(cls, symbol):
        return bool(cls._OPT.match(str(symbol or "").upper().strip()))

    # ---- live broker state (source of truth) ---------------------------------------------------

    def _positions(self, book):
        """{symbol: qty} for the legacy targets currently held on the account."""
        rj = (book.positions().get("response_json") or {})
        out = {}
        for p in (rj.get("Positions") or []):
            sym = p.get("Symbol")
            if sym in self.TARGETS:
                q = int(self._f(p.get("Quantity")))
                if q > 0:
                    out[sym] = q
        return out

    _ACTIVE = {"Queued", "Received", "Open", "Sending", "Partially Filled", "Accepted"}

    def _working_sells(self, book, symbol):
        """[(order_id, limit_price, order_type)] of live SELL orders resting on this symbol."""
        rj = (book.orders().get("response_json") or {})
        out = []
        for o in (rj.get("Orders") or []):
            if o.get("StatusDescription") not in self._ACTIVE:
                continue
            leg = (o.get("Legs") or [{}])[0]
            if leg.get("Symbol") == symbol and str(leg.get("BuyOrSell")) == "Sell":
                out.append((o.get("OrderID"), self._f(o.get("LimitPrice")), o.get("OrderType")))
        return out

    # ---- session clock -------------------------------------------------------------------------

    def _minutes_since_open(self, now=None):
        """Minutes since the session first opened today. Marker-based so it is DST-proof and does
        not assume the scheduler cadence."""
        now = now or datetime.utcnow()
        today = now.date().isoformat()
        rec = {}
        try:
            rec = json.loads(self.SESSION_MARKER.read_text())
        except Exception:
            rec = {}
        if rec.get("date") != today or not rec.get("open_utc"):
            rec = {"date": today, "open_utc": now.isoformat()}
            try:
                self.SESSION_MARKER.parent.mkdir(parents=True, exist_ok=True)
                self.SESSION_MARKER.write_text(json.dumps(rec))
            except Exception:
                pass
        try:
            opened = datetime.fromisoformat(rec["open_utc"])
            return max(0.0, (now - opened).total_seconds() / 60.0)
        except Exception:
            return 0.0

    # ---- desired close price -------------------------------------------------------------------

    def _desired(self, symbol, bid, ask, minutes):
        """(order_type, limit_price, action, urgency) for this symbol's close this cycle."""
        if not self._is_option(symbol):
            # equity: marketable limit just below the live bid — fills at the open cross, chases a
            # gap-down down each cycle. Tiny spread, nothing to capture.
            return ("Limit", round(bid * self.EQUITY_MARKETABLE_FRAC, 2), "SELL", "equity")
        from app.services.options_exit_execution_engine import OptionsExitExecutionEngine
        px = OptionsExitExecutionEngine()
        if minutes < self.PATIENT_UNTIL_MIN:
            p = px.price_exit(bid, ask, reason="LEGACY_LIQUIDATION", urgency="patient")
            return (p["order_type"], p["limit_price"], "SELLTOCLOSE", "patient")
        if minutes < self.MID_UNTIL_MIN:
            # meet the market at the mid, on the option's tick grid
            from app.services.options_entry_forecast_engine import OptionsEntryForecastEngine
            tick = OptionsEntryForecastEngine._tick_for(bid, ask) or 0.05
            mid = round(round(((bid + ask) / 2) / tick) * tick, 2)
            return ("Limit", mid, "SELLTOCLOSE", "mid")
        # urgent: marketable limit at the bid — guaranteed fill, bid as a floor
        p = px.price_exit(bid, ask, reason="LEGACY_LIQUIDATION_STOP", urgency="urgent")
        return (p["order_type"], p["limit_price"], "SELLTOCLOSE", "urgent")

    # ---- main cycle ----------------------------------------------------------------------------

    def run_cycle(self, is_regular_session=True):
        if not self.enabled():
            return {"status": "LEGACY_LIQUIDATION_DISABLED", "managed": 0}
        if not is_regular_session:
            return {"status": "LEGACY_LIQUIDATION_MARKET_CLOSED", "managed": 0}

        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        book = TradeStationSimBookingEngine()
        quotes = TradeStationQuoteLiveEngine()

        held = self._positions(book)
        if not held:
            return {"status": "LEGACY_LIQUIDATION_FLAT", "managed": 0,
                    "note": "no legacy targets held — nothing to liquidate"}

        minutes = self._minutes_since_open()
        actions = []
        for symbol, qty in held.items():
            try:
                rj = (quotes.get_quote(symbol.split()[0] if not self._is_option(symbol) else symbol)
                      .get("response_json") or {})
                row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
                bid, ask = self._f(row.get("Bid")), self._f(row.get("Ask"))
                if bid <= 0:
                    actions.append({"symbol": symbol, "skipped": "no live bid"})
                    continue
                otype, limit, action, urgency = self._desired(symbol, bid, ask, minutes)
                if not limit or limit <= 0:
                    actions.append({"symbol": symbol, "skipped": "no usable price"})
                    continue

                existing = self._working_sells(book, symbol)
                # leave a good resting close in place — no churn
                if len(existing) == 1 and existing[0][1] > 0 and \
                        abs(existing[0][1] - limit) <= self.REPRICE_TOL * limit:
                    actions.append({"symbol": symbol, "held": qty, "urgency": urgency,
                                    "limit": existing[0][1], "action": "kept"})
                    continue

                # otherwise cancel every working sell, CONFIRM gone, then place exactly one
                for oid, _, _ in existing:
                    book.cancel_order(oid)
                if self._working_sells(book, symbol):
                    actions.append({"symbol": symbol, "skipped": "cancel not confirmed — retry next cycle"})
                    continue
                r = book.place_order(symbol, qty, action=action, order_type=otype,
                                     limit_price=limit, tif="GTC")
                actions.append({"symbol": symbol, "held": qty, "urgency": urgency, "limit": limit,
                                "action": "repriced", "ok": r.get("ok"), "order_id": r.get("order_id")})
            except Exception as exc:
                actions.append({"symbol": symbol, "error": repr(exc)[:120]})

        return {"status": "LEGACY_LIQUIDATION_MANAGED", "managed": len(held),
                "minutes_since_open": round(minutes, 1), "actions": actions,
                "timestamp": datetime.utcnow().isoformat()}
