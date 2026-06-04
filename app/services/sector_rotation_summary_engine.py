from datetime import datetime

from app.services.sector_rotation_engine import SectorRotationEngine


class SectorRotationSummaryEngine:

    def summarize(self):
        rotation = SectorRotationEngine().evaluate_sectors()
        rankings = rotation.get("rankings", [])

        top_sector = rankings[0] if rankings else None

        strong = [
            item for item in rankings
            if item.get("momentum_score", 0) >= 75
        ]

        weak = [
            item for item in rankings
            if item.get("momentum_score", 0) < 50
        ]

        risk_on_symbols = {"XLK", "SMH", "QQQ", "IWM", "XLY", "IBIT", "ETHE"}
        defensive_symbols = {"XLP", "XLU", "XLV"}

        risk_on_count = len([
            item for item in strong
            if item.get("symbol") in risk_on_symbols
        ])

        defensive_count = len([
            item for item in strong
            if item.get("symbol") in defensive_symbols
        ])

        if risk_on_count > defensive_count:
            market_bias = "RISK_ON_ROTATION"
        elif defensive_count > risk_on_count:
            market_bias = "DEFENSIVE_ROTATION"
        else:
            market_bias = "MIXED_ROTATION"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "top_sector": top_sector,
            "strong_sector_count": len(strong),
            "weak_sector_count": len(weak),
            "risk_on_count": risk_on_count,
            "defensive_count": defensive_count,
            "market_bias": market_bias,
            "execution_enabled": False,
            "status": "SECTOR_ROTATION_SUMMARY_READY"
        }
