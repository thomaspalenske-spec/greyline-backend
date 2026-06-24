from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PortfolioDirectionalExposureEngine:

    def evaluate(self):
        exposure = PortfolioExposureEngine().evaluate()
        positions = exposure.get("positions", [])

        long_notional = 0.0
        short_notional = 0.0

        for p in positions:
            notional = float(p.get("notional") or 0)
            bias = str(p.get("directional_bias") or "").upper()

            if bias == "BEARISH":
                short_notional += notional
            else:
                long_notional += notional

        gross_exposure = long_notional + short_notional
        net_exposure = long_notional - short_notional

        long_pct = round((long_notional / gross_exposure) * 100, 2) if gross_exposure else 0
        short_pct = round((short_notional / gross_exposure) * 100, 2) if gross_exposure else 0
        net_pct = round((net_exposure / gross_exposure) * 100, 2) if gross_exposure else 0

        abs_net = abs(net_pct)

        if abs_net >= 80:
            directional_risk = "HIGH"
            action = "LIMIT_NEW_SAME_DIRECTION_EXPOSURE"
        elif abs_net >= 60:
            directional_risk = "ELEVATED"
            action = "REDUCE_NEW_SAME_DIRECTION_EXPOSURE"
        elif abs_net >= 35:
            directional_risk = "MODERATE"
            action = "MONITOR_DIRECTIONAL_BALANCE"
        else:
            directional_risk = "LOW"
            action = "DIRECTIONAL_BALANCE_HEALTHY"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioDirectionalExposureEngine",
            "gross_exposure": round(gross_exposure, 2),
            "long_notional": round(long_notional, 2),
            "short_notional": round(short_notional, 2),
            "gross_long_exposure_pct": long_pct,
            "gross_short_exposure_pct": short_pct,
            "net_exposure_pct": net_pct,
            "directional_risk": directional_risk,
            "recommended_action": action,
            "positions": positions,
            "status": "PORTFOLIO_DIRECTIONAL_EXPOSURE_READY",
        }
