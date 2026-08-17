#!/usr/bin/env python3
"""READ-ONLY diagnostic: dump the shape of multi-leg (condor) orders from the SIM order history.

Places NOTHING. Used to verify the per-leg fill payload the VRP close reads (ExecutionPrice signed by
BuyOrSell). Run it after a real atomic condor fills to confirm ExecutionPrice is POPULATED (a number),
which flips the recorded realized_pnl_basis from 'close_order' (conservative) to 'fills' (exact).

    python scripts/capture_multileg_fill_shape.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine


def main():
    orders = ((TradeStationSimBookingEngine().orders().get("response_json") or {}).get("Orders") or [])
    multi = [o for o in orders if isinstance(o.get("Legs"), list) and len(o.get("Legs") or []) > 1]
    print(f"orders in history: {len(orders)} | multi-leg: {len(multi)}")
    for o in multi:
        legs = o.get("Legs") or []
        filled = [lg for lg in legs if (lg.get("ExecutionPrice") not in (None, "", "0", 0))]
        print(f"\nOrderID {o.get('OrderID')} · {o.get('StatusDescription')} · "
              f"FilledPrice={o.get('FilledPrice')} · {len(filled)}/{len(legs)} legs priced "
              f"· {'FILLED-EXAMPLE ✓' if filled else 'no executions (rejected/open)'}")
        for lg in legs:
            print("   ", {k: lg.get(k) for k in ("Symbol", "BuyOrSell", "OpenOrClose",
                  "QuantityOrdered", "ExecQuantity", "ExecutionPrice")})
    if not any(lg.get("ExecutionPrice") not in (None, "", "0", 0)
               for o in multi for lg in (o.get("Legs") or [])):
        print("\nNo FILLED multi-leg example yet — re-run after a real atomic condor fills to confirm "
              "ExecutionPrice populates (then VRP realized_pnl_basis becomes 'fills').")


if __name__ == "__main__":
    main()
