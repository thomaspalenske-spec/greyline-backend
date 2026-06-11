from datetime import datetime


class GreyLinePortfolioAllocationEngine:

    def allocate(self, signals, available_capital=10000):

        allocations = []
        total_risk_budget = 0.10  # 10% system risk cap baseline

        per_trade_budget = available_capital * total_risk_budget

        for signal in signals.get("signals", []):

            symbol = signal.get("symbol")
            decision = signal.get("signal")
            change_pct = signal.get("change_pct")

            allocation = 0

            # Core allocation logic (simple risk-weighted sizing)
            if decision == "TAKE_PROFIT":
                allocation = 0
            elif decision == "CUT_LOSS":
                allocation = per_trade_budget * 0.5
            elif decision == "HOLD_WINNER":
                allocation = per_trade_budget * 1.2
            elif decision == "HOLD_LOSER":
                allocation = per_trade_budget * 0.3
            else:
                allocation = per_trade_budget * 0.5

            allocations.append({
                "symbol": symbol,
                "decision": decision,
                "allocation": round(allocation, 2),
                "allocation_pct": round((allocation / available_capital) * 100, 2),
                "signal_strength": change_pct
            })

        total_allocated = sum(a["allocation"] for a in allocations)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "available_capital": available_capital,
            "total_allocated": round(total_allocated, 2),
            "allocations": allocations,
            "status": "PORTFOLIO_ALLOCATION_COMPLETE"
        }
