"""In-flight (working, unfilled) order guard — the shared fix for the rebalance-churn loop.

A vol-target / trend sleeve sizes `delta = target - held`, where `held` is the FILLED broker
position. A patient DAY limit that rests unfilled is invisible to that read, so every ~10-minute
scheduler cycle the sleeve re-posts the SAME shortfall on top of a lagged read. The duplicate DAY
limits stack; when the market finally reaches them they all fill at once, the position massively
overshoots target, and the sleeve dumps the excess — then the loop repeats. Observed live 2026-08-04:
carry stacked SVXY to 154 shares (buy 20 nearly every cycle) before a single 154-share dump; trend
did the same on QQQM / IWM / EFA / DBC.

The fix is to count a sleeve's OWN resting orders as part of its effective position:

    effective = filled_held + net_working(symbol)      # +buys, -sells, over UNFILLED remainders

so a shortfall that already has an order resting for it yields delta ~= 0 and no duplicate order.

Truthful and drift-free: a working order is counted here until it fills, at which point it leaves
`working` and reappears in `held` — never double-counted, never a phantom (unlike an order-COUNT
tally, which can't tell a fill from a cancel). On a DEGRADED / failed orders read `ok=False` and the
`net` map is empty — callers MUST refuse to open on `ok=False`, because they cannot rule out a
resting duplicate (acting blind is exactly how the stack builds)."""

from datetime import datetime


class InFlightOrdersEngine:

    # StatusDescriptions that still reserve / will still consume shares. Mirrors the set the broker
    # protective-stop engine treats as "working" so the two agree on what a live resting order is.
    WORKING = ("received", "open", "queued", "sent", "partiallyfilled", "pending")

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _booking(cls):
        from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
        return TradeStationSimBookingEngine()

    @classmethod
    def snapshot(cls, booking=None):
        """One orders read -> {"ok": bool, "net": {SYMBOL: signed_unfilled_qty}, "count": working_orders}.

        signed qty: +buy / -sell, over each working order's UNFILLED remainder (QuantityRemaining,
        falling back to Quantity). ok=False on any read error or a broker-flagged non-ok read; the net
        map is then empty and the caller must not open on it."""
        try:
            b = booking or cls._booking()
            resp = b.orders()
        except Exception as e:
            return {"ok": False, "net": {}, "count": 0, "detail": f"orders read failed: {str(e)[:120]}"}
        if not bool(resp.get("ok", True)):
            return {"ok": False, "net": {}, "count": 0, "detail": "orders read degraded (broker not-ok)"}
        ords = (resp.get("response_json") or {}).get("Orders") or []
        net, working = {}, 0
        for o in ords:
            if str(o.get("StatusDescription", "")).lower() not in cls.WORKING:
                continue
            for leg in (o.get("Legs") or []):
                sym = str(leg.get("Symbol") or "").upper()
                if not sym:
                    continue
                qty = cls._f(leg.get("QuantityRemaining"))
                if qty == 0:                       # no remainder field -> fall back to full quantity
                    qty = cls._f(leg.get("Quantity"))
                side = str(leg.get("BuyOrSell") or "").lower()
                signed = qty if side.startswith("buy") else (-qty if side.startswith("sell") else 0)
                if signed:
                    net[sym] = net.get(sym, 0.0) + signed
                    working += 1
        return {"ok": True, "net": {k: int(round(v)) for k, v in net.items()}, "count": working}

    @classmethod
    def net_working(cls, symbol, booking=None, snapshot=None):
        """Convenience for a single symbol. Pass a shared `snapshot` to avoid re-reading orders when
        sizing a whole basket. Returns {"ok": bool, "net": int}."""
        snap = snapshot if snapshot is not None else cls.snapshot(booking=booking)
        return {"ok": snap["ok"], "net": int(snap["net"].get(str(symbol).upper(), 0))}

    @classmethod
    def status(cls):
        snap = cls.snapshot()
        return {"timestamp": datetime.utcnow().isoformat(), **snap,
                "note": ("Net signed UNFILLED working-order qty per symbol (+buy/-sell). Sleeves add this "
                         "to filled `held` so a resting order isn't re-ordered next cycle (churn guard). "
                         "ok=False -> orders read degraded, sleeves must not open.")}
