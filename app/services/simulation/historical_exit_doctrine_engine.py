from datetime import datetime

from app.services.dynamic_exit_policy_engine import DynamicExitPolicyEngine
from app.services.dynamic_tp_management_engine import DynamicTPManagementEngine
from app.services.simulation.historical_exit_policy_optimizer import HistoricalExitPolicyOptimizer


class HistoricalExitDoctrineEngine:
    """
    Simulator-only GreyLine exit doctrine wrapper.

    Purpose:
    - Keep historical simulation aligned with GreyLine OS exit logic.
    - Do not modify live/paper execution engines.
    - Centralize dynamic stop, reward/risk TP, TP ladder, runner, and exit policy.
    """

    def build(self, symbol, signal, entry_price, current_price=None, unrealized_pct=0):
        current_price = current_price or entry_price

        dynamic_exit_policy = DynamicExitPolicyEngine().build_policy(
            symbol=symbol,
            composite_score=signal.get("composite_score"),
        )

        stop_loss_pct = float(dynamic_exit_policy.get("stop_loss_pct") or -5.0)
        take_profit_pct = float(dynamic_exit_policy.get("take_profit_pct") or abs(stop_loss_pct) * 2.5)

        dynamic_trade = {
            "entry_price": entry_price,
            "current_price": current_price,
            "asset_type": "EQUITY",
            "take_profit_pct": take_profit_pct,
            "volatility_score": dynamic_exit_policy.get("volatility_score") or signal.get("volatility_score") or 50,
            "unrealized_pnl_pct": unrealized_pct,
        }

        dynamic_tp = DynamicTPManagementEngine().evaluate(dynamic_trade)

        exit_policy = HistoricalExitPolicyOptimizer().choose(
            regime_score=signal.get("regime_score") or 0,
            risk_state_score=signal.get("risk_state_score") or 0,
            direction_confidence=signal.get("direction_confidence") or 0,
            volatility_score=signal.get("volatility_score") or dynamic_exit_policy.get("volatility_score") or 0,
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "doctrine": "GREYLINE_HISTORICAL_EXIT_DOCTRINE",
            "dynamic_exit_policy": dynamic_exit_policy,
            "dynamic_tp": dynamic_tp,
            "exit_policy": exit_policy,
            "stop_loss_pct": round(stop_loss_pct, 2),
            "take_profit_pct": round(take_profit_pct, 2),
            "volatility_score": dynamic_trade["volatility_score"],
            "status": "HISTORICAL_EXIT_DOCTRINE_READY",
        }

    def tp_return_thresholds(self, doctrine, entry_price, direction="BULLISH", option_type=""):
        dynamic_tp = doctrine.get("dynamic_tp") or {}

        tp1_price = dynamic_tp.get("dynamic_tp1_price")
        tp2_price = dynamic_tp.get("dynamic_tp2_price")
        tp3_price = dynamic_tp.get("dynamic_tp3_price")

        if not entry_price or not tp1_price or not tp2_price or not tp3_price:
            take_profit_pct = float(doctrine.get("take_profit_pct") or 10)
            return {
                "tp1_pct": round(take_profit_pct * 0.25, 2),
                "tp2_pct": round(take_profit_pct * 0.50, 2),
                "tp3_pct": round(take_profit_pct * 0.75, 2),
            }

        bearish = str(direction).upper() == "BEARISH" or str(option_type).upper() == "PUT"

        if bearish:
            tp1_pct = abs(((entry_price - tp1_price) / entry_price) * 100)
            tp2_pct = abs(((entry_price - tp2_price) / entry_price) * 100)
            tp3_pct = abs(((entry_price - tp3_price) / entry_price) * 100)
        else:
            tp1_pct = ((tp1_price - entry_price) / entry_price) * 100
            tp2_pct = ((tp2_price - entry_price) / entry_price) * 100
            tp3_pct = ((tp3_price - entry_price) / entry_price) * 100

        return {
            "tp1_pct": round(tp1_pct, 2),
            "tp2_pct": round(tp2_pct, 2),
            "tp3_pct": round(tp3_pct, 2),
        }
