from datetime import datetime

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PortfolioConflictEngine:

    CONFLICT_PAIRS = {
        ("XLE", "XLU"): "ENERGY_VS_UTILITIES_MACRO_OPPOSITION",
        ("XLU", "XLE"): "UTILITIES_VS_ENERGY_MACRO_OPPOSITION",
        ("TLT", "KRE"): "RATES_DURATION_VS_REGIONAL_BANKS",
        ("KRE", "TLT"): "REGIONAL_BANKS_VS_RATES_DURATION",
        ("SPY", "SQQQ"): "BROAD_MARKET_LONG_VS_NASDAQ_SHORT",
        ("QQQ", "SQQQ"): "NASDAQ_LONG_VS_NASDAQ_SHORT",
        ("SPY", "SH"): "BROAD_MARKET_LONG_VS_SP500_SHORT",
    }

    def evaluate(self, candidate_symbol=None):
        exposure = PortfolioExposureEngine().evaluate()
        positions = exposure.get("positions", [])

        existing_symbols = [
            str(p.get("symbol") or "").upper().strip()
            for p in positions
            if p.get("symbol")
        ]

        candidate = str(candidate_symbol or "").upper().strip() or None

        conflicts = []

        symbols_to_check = existing_symbols[:]

        if candidate:
            symbols_to_check.append(candidate)

        for i, left in enumerate(symbols_to_check):
            for right in symbols_to_check[i + 1:]:
                conflict_type = self.CONFLICT_PAIRS.get((left, right))
                if conflict_type:
                    conflicts.append({
                        "existing_position": left if left in existing_symbols else right,
                        "candidate": candidate,
                        "conflict_pair": [left, right],
                        "conflict_type": conflict_type,
                        "severity": "HIGH",
                    })

        conflict_count = len(conflicts)

        if conflict_count >= 2:
            conflict_score = 85
            conflict_state = "HIGH"
            action = "BLOCK_OR_REDUCE_CONFLICTING_EXPOSURE"
            multiplier = 0.5
        elif conflict_count == 1:
            conflict_score = 65
            conflict_state = "ELEVATED"
            action = "REDUCE_CONFLICTING_EXPOSURE"
            multiplier = 0.75
        else:
            conflict_score = 0
            conflict_state = "LOW"
            action = "NO_PORTFOLIO_CONFLICT_DETECTED"
            multiplier = 1.0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioConflictEngine",
            "candidate_symbol": candidate,
            "open_symbols": existing_symbols,
            "conflict_count": conflict_count,
            "conflict_score": conflict_score,
            "conflict_state": conflict_state,
            "allocation_multiplier": multiplier,
            "recommended_action": action,
            "conflicts": conflicts,
            "status": "PORTFOLIO_CONFLICT_READY",
        }
