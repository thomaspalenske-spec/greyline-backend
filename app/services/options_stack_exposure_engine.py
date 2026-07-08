from collections import defaultdict
from datetime import datetime

from app.services.options_account_dashboard_engine import OptionsAccountDashboardEngine


class OptionsStackExposureEngine:
    def evaluate(self):
        d = OptionsAccountDashboardEngine().build()
        groups = defaultdict(list)

        for p in d.get("open_positions", []):
            key = (
                str(p.get("underlying") or "").upper(),
                str(p.get("option_type") or "").upper(),
            )
            groups[key].append(p)

        stacked = []
        for (underlying, option_type), positions in groups.items():
            if len(positions) > 1:
                stacked.append({
                    "underlying": underlying,
                    "option_type": option_type,
                    "open_count": len(positions),
                    "total_cost": round(sum(float(p.get("estimated_cost") or 0) for p in positions), 2),
                    "total_pnl": round(sum(float(p.get("unrealized_pnl") or 0) for p in positions), 2),
                    "positions": [
                        {
                            "option_symbol": p.get("option_symbol"),
                            "contracts": p.get("contracts"),
                            "cost": p.get("estimated_cost"),
                            "pnl": p.get("unrealized_pnl"),
                            "pnl_pct": p.get("unrealized_pnl_pct"),
                            "stage": p.get("position_stage"),
                        }
                        for p in positions
                    ],
                })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "OptionsStackExposureEngine",
            "stacked_exposure_detected": len(stacked) > 0,
            "stacked_group_count": len(stacked),
            "stacked_groups": stacked,
            "status": "OPTIONS_STACK_EXPOSURE_READY",
        }
