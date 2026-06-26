
from datetime import datetime


class SimulationEquityCurveEngine:
    """
    Tracks simulated account equity after every completed trade.

    Input:
        trades = [
            {
                "return_pct": 3.5
            },
            ...
        ]

    Returns:
        Running equity statistics.
    """

    def evaluate(self, trades, starting_capital=100000):

        equity = float(starting_capital)

        peak_equity = equity
        max_drawdown_pct = 0

        curve = []

        for trade in trades:

            r = float(trade.get("return_pct") or 0)

            equity *= (1 + r / 100)

            if equity > peak_equity:
                peak_equity = equity

            drawdown = (
                (peak_equity - equity) /
                peak_equity
            ) * 100

            max_drawdown_pct = max(
                max_drawdown_pct,
                drawdown
            )

            curve.append({
                "timestamp": trade.get("exit_timestamp"),
                "equity": round(equity, 2),
                "return_pct": r
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "SimulationEquityCurveEngine",
            "starting_capital": round(starting_capital, 2),
            "ending_capital": round(equity, 2),
            "net_profit": round(equity - starting_capital, 2),
            "net_return_pct": round(
                ((equity / starting_capital) - 1) * 100,
                2
            ),
            "peak_equity": round(peak_equity, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "curve": curve,
            "status": "SIMULATION_EQUITY_CURVE_READY",
        }
