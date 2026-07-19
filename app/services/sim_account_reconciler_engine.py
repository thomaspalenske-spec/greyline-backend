"""
Reads the ACTUAL state of the TradeStation SIMULATED account — balances, open
positions, working orders — and normalizes it for display. This is what lets the
dashboard show real broker-simulated truth (fills, avg price, unrealized P&L) instead
of the internal ledger. Read-only; goes through the sandbox-guarded booking engine.
"""

from datetime import datetime

from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class SimAccountReconcilerEngine:

    def __init__(self):
        self.booking = TradeStationSimBookingEngine()

    def snapshot(self):
        bal = self.booking.balances()
        pos = self.booking.positions()
        ords = self.booking.orders()

        balances = ((bal.get("response_json") or {}).get("Balances") or [{}])
        b = balances[0] if balances else {}
        positions = (pos.get("response_json") or {}).get("Positions") or []
        orders = (ords.get("response_json") or {}).get("Orders") or []
        working = [o for o in orders
                   if str(o.get("StatusDescription", "")).lower() in
                   ("received", "open", "queued", "sent", "partiallyfilled")]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "environment": "SANDBOX",
            "source": "TradeStation SIM",
            "reads_ok": bool(bal.get("ok") and pos.get("ok") and ords.get("ok")),
            "account_id": b.get("AccountID"),
            "equity": _f(b.get("Equity")),
            "cash_balance": _f(b.get("CashBalance")),
            "buying_power": _f(b.get("BuyingPower")),
            "position_count": len(positions),
            "working_order_count": len(working),
            "positions": [{
                "symbol": p.get("Symbol"),
                "quantity": _f(p.get("Quantity")),
                "avg_price": _f(p.get("AveragePrice")),
                "last": _f(p.get("Last")),
                "market_value": _f(p.get("MarketValue")),
                "unrealized_pl": _f(p.get("UnrealizedProfitLoss")),
                "long_short": p.get("LongShort"),
            } for p in positions],
        }
