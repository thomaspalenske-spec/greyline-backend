"""Resting DISASTER stops at the broker — protection that survives GreyLine being dead.

Every exit GreyLine has is evaluated in software: the ATR doctrine, the take-profit ladder, the
maturity liquidation. All of it requires the scheduler to be running. If this machine sleeps,
crashes, loses network, or the process dies, open positions have NO protection at all — the
stop exists only as an intention inside a program that is not executing.

Institutional practice is never to rely on your own software being up to manage risk. A resting
order at the broker executes whether or not you exist.

THIS IS A FAILSAFE, NOT THE STRATEGY'S STOP. It sits deliberately FAR below the doctrine's
2.5-ATR stop, so in normal operation the software always exits first and this never fires. It
exists for the case where the software is not there to exit at all. Setting it near the
doctrine level would cause the two to race and would replace a considered exit with a dumb one.

THE DOUBLE-SELL HAZARD, HANDLED EXPLICITLY:
A resting sell plus a software sell can liquidate the same position twice — which at a broker
means going SHORT. That exact bug (closing sized from a ledger count rather than the live
position) already happened here once and was rejected by TradeStation. So:
  * the protective order is CANCELLED BEFORE any software-initiated close, never alongside it
  * quantity always comes from the LIVE broker position, never from a ledger
  * one resting stop per symbol, verified against working orders before placing another

DEFAULT OFF. This engine places real orders, and switching on new order-placing behaviour
silently is not acceptable. Enable with GREYLINE_BROKER_PROTECTIVE_STOPS=true.
"""

from datetime import datetime
from os import getenv


class BrokerProtectiveStopEngine:

    # Deliberately wide: the doctrine stop is ~2.5 ATR (typically 8-20%). This only fires when
    # nothing else can, so it must never pre-empt a considered exit.
    DISASTER_STOP_PCT = 0.35        # 35% below entry for a long
    WORKING = ("received", "open", "queued", "sent", "partiallyfilled")

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_BROKER_PROTECTIVE_STOPS", "") or "").strip().lower() == "true"

    def _booking(self):
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        return TradeStationSimBookingEngine()

    def _live_state(self, b):
        pos = (b.positions().get("response_json") or {}).get("Positions") or []
        ords = (b.orders().get("response_json") or {}).get("Orders") or []
        working = [o for o in ords
                   if str(o.get("StatusDescription", "")).lower() in self.WORKING]
        # Symbols with ANY working sell order are off-limits, not just those with a stop.
        # A position already being closed (a working SELLTOCLOSE) must NOT also get a stop:
        # both could fill and the position would be sold twice, flipping SHORT. That is the
        # same double-sell class of bug that TradeStation rejected here once before.
        protected, closing = set(), set()
        for o in working:
            leg = (o.get("Legs") or [{}])[0]
            sym = str(leg.get("Symbol") or "").upper()
            if not str(leg.get("BuyOrSell") or "").lower().startswith("sell"):
                continue
            if "stop" in str(o.get("OrderType") or "").lower():
                protected.add(sym)
            else:
                closing.add(sym)          # working close — do not stack a stop on it
        return pos, working, protected, closing

    @staticmethod
    def _vrp_leg_symbols():
        """Symbols that are legs of an OPEN VRP defined-risk condor. These must NEVER get a broker
        stop: the wings ARE the risk cap, so stopping a wing leaves the short leg NAKED (undefined
        risk) — the exact opposite of protection. The condor is already defined-risk by structure."""
        import json
        from pathlib import Path
        out = set()
        try:
            for ln in Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl").read_text().splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                if str(r.get("status")).upper() != "OPEN":
                    continue
                for lg in r.get("legs", []) or []:
                    s = str(lg.get("symbol") or "").upper()
                    if s:
                        out.add(s)
        except Exception:
            pass
        return out

    @staticmethod
    def _tick_round(price, is_option):
        """Options quote on a $0.05 grid (TradeStation rejects off-grid); equities on $0.01."""
        if is_option:
            return round(round(price / 0.05) * 0.05, 2)
        return round(price, 2)

    def ensure_stops(self, dry_run=False):
        """Place a resting disaster stop for any live long position that lacks one."""
        if not self.enabled():
            return {"status": "PROTECTIVE_STOPS_DISABLED", "placed": 0,
                    "detail": "set GREYLINE_BROKER_PROTECTIVE_STOPS=true to arm broker-side "
                              "protection; without it, positions are unprotected whenever "
                              "GreyLine is not running"}
        b = self._booking()
        pos, working, protected, closing = self._live_state(b)
        vrp_legs = self._vrp_leg_symbols()   # never stop a defined-risk condor's own legs

        placed, skipped, errors = [], [], []
        for p in pos:
            sym = str(p.get("Symbol") or "")
            qty = int(float(p.get("Quantity") or 0))          # LIVE broker qty, never a ledger
            entry = float(p.get("AveragePrice") or 0)
            is_short = str(p.get("LongShort") or "").lower() == "short"
            if qty <= 0 or entry <= 0 or is_short:
                skipped.append({"symbol": sym, "reason": "not a long position"})
                continue
            if sym.upper() in vrp_legs:
                # a condor WING: stopping it out would strand the short leg naked. The condor's
                # defined-risk structure IS its protection; a broker stop here is actively harmful.
                skipped.append({"symbol": sym, "reason": "VRP condor leg — defined-risk, must not be stopped"})
                continue
            if sym.upper() in protected:
                skipped.append({"symbol": sym, "reason": "already protected"})
                continue
            if sym.upper() in closing:
                # a close is already working; a stop alongside it could double-sell
                skipped.append({"symbol": sym, "reason": "close already working — stop would risk a double sell"})
                continue

            is_option = " " in sym
            stop_px = self._tick_round(entry * (1 - self.DISASTER_STOP_PCT), is_option)
            if stop_px <= 0:
                skipped.append({"symbol": sym, "reason": "computed stop <= 0"})
                continue
            if dry_run:
                placed.append({"symbol": sym, "qty": qty, "stop": stop_px, "dry_run": True})
                continue
            try:
                r = b.place_order(sym, qty,
                                  action="SELLTOCLOSE" if is_option else "SELL",
                                  order_type="StopMarket", stop_price=stop_px, tif="GTC")
                if r.get("ok"):
                    placed.append({"symbol": sym, "qty": qty, "stop": stop_px,
                                   "order_id": r.get("order_id")})
                else:
                    errors.append({"symbol": sym, "http": r.get("http_status")})
            except Exception as e:
                errors.append({"symbol": sym, "error": str(e)[:80]})

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "disaster_stop_pct": self.DISASTER_STOP_PCT,
            "positions_seen": len(pos), "placed": len(placed), "placed_detail": placed[:10],
            "skipped": skipped[:10], "errors": errors[:10],
            "note": ("failsafe only — sits far below the doctrine's ATR stop so software exits "
                     "always fire first; this covers the case where software cannot fire at all"),
            "status": "PROTECTIVE_STOPS_ENSURED",
        }

    def clear_stop(self, symbol):
        """Cancel the resting protective order BEFORE a software close.

        Must be called first by any exit path. Leaving it working while also selling in
        software is how a position gets liquidated twice and flips SHORT.
        """
        b = self._booking()
        _, working, _, _ = self._live_state(b)
        target = str(symbol or "").upper()
        cancelled, errors = [], []
        for o in working:
            leg = (o.get("Legs") or [{}])[0]
            if str(leg.get("Symbol") or "").upper() != target:
                continue
            if "stop" not in str(o.get("OrderType") or "").lower():
                continue
            try:
                r = b.cancel_order(o.get("OrderID"))
                (cancelled if r.get("http_status") in (200, 201)
                 else errors).append(o.get("OrderID"))
            except Exception as e:
                errors.append({"order_id": o.get("OrderID"), "error": str(e)[:60]})
        return {"symbol": symbol, "cancelled": cancelled, "errors": errors,
                "status": "PROTECTIVE_STOP_CLEARED" if cancelled else "NO_PROTECTIVE_STOP_FOUND"}

    def status(self):
        b = self._booking()
        try:
            pos, working, protected, closing = self._live_state(b)
        except Exception as e:
            return {"status": "BROKER_READ_FAILED", "error": str(e)[:100]}
        longs = [str(p.get("Symbol") or "").upper() for p in pos
                 if int(float(p.get("Quantity") or 0)) > 0
                 and str(p.get("LongShort") or "").lower() != "short"]
        unprotected = [s for s in longs if s not in protected and s not in closing]
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "enabled": self.enabled(),
            "long_positions": len(longs),
            "protected_at_broker": len([s for s in longs if s in protected]),
            "unprotected": unprotected,
            "closing_not_stopped": sorted(closing & set(longs)),
            "exposure_note": ("unprotected positions have NO stop if GreyLine stops running — "
                              "every doctrine exit requires the scheduler to be alive"),
            "status": "PROTECTIVE_STOP_STATUS",
        }
