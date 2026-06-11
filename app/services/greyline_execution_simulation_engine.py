from datetime import datetime
import random


class GreyLineExecutionSimulationEngine:

    def execute(self, allocations, current_positions):

        executed_trades = []
        updated_positions = []

        slippage_bps = 0.02  # 0.02% baseline slippage

        for alloc in allocations.get("allocations", []):

            symbol = alloc.get("symbol")
            allocation = alloc.get("allocation")

            if allocation <= 0:
                continue

            fill_price_impact = random.uniform(-slippage_bps, slippage_bps)

            fill_price = 100 * (1 + fill_price_impact)

            quantity = allocation / fill_price

            executed_trade = {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "fill_price": round(fill_price, 4),
                "allocation": allocation,
                "quantity": round(quantity, 4),
                "slippage_bps": round(fill_price_impact * 100, 4),
                "event_type": "SIMULATED_FILL"
            }

            executed_trades.append(executed_trade)

            updated_positions.append({
                "symbol": symbol,
                "entry_price": fill_price,
                "quantity": quantity,
                "state": "ACTIVE",
                "origin": "SIMULATED_EXECUTION"
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "executed_trades": executed_trades,
            "updated_positions": updated_positions,
            "trade_count": len(executed_trades),
            "status": "EXECUTION_SIMULATION_COMPLETE"
        }
