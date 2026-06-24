from datetime import datetime

from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine


class PortfolioHeatEngine:

    MAX_PORTFOLIO_HEAT_PCT = 25.0

    def evaluate(self):

        ledger = PaperTradeLedgerEngine().history()

        open_positions = [
            t for t in ledger.get("trades", [])
            if t.get("status") == "OPEN"
        ]

        portfolio_heat = 0.0

        position_risks = []

        for trade in open_positions:

            notional = float(
                trade.get("current_price")
                or trade.get("entry_price")
                or 0
            )

            stop_pct = abs(
                float(trade.get("stop_loss_pct") or 0)
            )

            risk_pct = stop_pct / 100.0

            position_heat = round(
                notional * risk_pct,
                2
            )

            portfolio_heat += position_heat

            position_risks.append({
                "symbol": trade.get("symbol"),
                "notional": notional,
                "stop_loss_pct": stop_pct,
                "position_heat": position_heat,
            })

        heat_pct = round(
            (portfolio_heat / 1000.0) * 100,
            2
        )

        remaining_budget = round(
            max(
                0,
                self.MAX_PORTFOLIO_HEAT_PCT - heat_pct
            ),
            2
        )

        if heat_pct >= 25:
            state = "CRITICAL"
            action = "BLOCK_NEW_DEPLOYMENT"

        elif heat_pct >= 18:
            state = "ELEVATED"
            action = "REDUCE_POSITION_SIZES"

        elif heat_pct >= 10:
            state = "MODERATE"
            action = "MONITOR_RISK_BUDGET"

        else:
            state = "NORMAL"
            action = "NORMAL_DEPLOYMENT"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioHeatEngine",
            "portfolio_heat_pct": heat_pct,
            "max_allowed_heat_pct": self.MAX_PORTFOLIO_HEAT_PCT,
            "remaining_risk_budget_pct": remaining_budget,
            "heat_state": state,
            "recommended_action": action,
            "positions": position_risks,
            "status": "PORTFOLIO_HEAT_READY",
        }
