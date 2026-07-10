from statistics import mean

from app.services.unusual_whales_operational_environment_engine import (
    UnusualWhalesOperationalEnvironmentEngine,
)


class InstitutionalIntelligenceEngine:

    def __init__(self):
        self.uw = UnusualWhalesOperationalEnvironmentEngine()

    @staticmethod
    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, float(v)))

    def analyze(self, symbol: str):
        d = self.uw.analyze(symbol)

        options_flow = d.get("options_flow") or {}
        alerts = d.get("flow_alerts") or {}
        strike = d.get("flow_by_strike") or {}
        expiry = d.get("flow_by_expiry") or {}
        dark = d.get("symbol_dark_pool") or {}
        gex = d.get("gex_levels") or {}
        greek = d.get("greek_exposure") or {}
        oi_change = d.get("open_interest_change") or {}
        oi_strike = d.get("open_interest_by_strike") or {}
        vrp = d.get("variance_risk_premium") or {}
        greek_flow = d.get("greek_flow") or {}
        spot = d.get("spot_exposures") or {}
        lit = d.get("lit_flow") or {}
        market_tide = d.get("market_tide") or {}
        sector_tide = d.get("sector_tide") or {}
        ownership = d.get("institutional_ownership") or {}
        shorts = d.get("short_volume") or {}
        insiders = d.get("insider_transactions") or {}
        congress = d.get("congress_trades") or {}

        buying = self._clamp(
            50
            + strike.get("directional_score", 0)
            + options_flow.get("directional_score", 0) / 2
        )

        selling = self._clamp(
            50
            - strike.get("directional_score", 0)
            - options_flow.get("directional_score", 0) / 2
        )

        dark_pool = self._clamp(
            (dark.get("total_premium", 0) / 1_000_000_000) * 25
        )

        dealer_gamma = 50
        latest = greek.get("latest") or {}
        net_gamma = latest.get("net_gamma")
        if net_gamma is not None:
            dealer_gamma = self._clamp(
                50 + max(-50, min(50, net_gamma / 100000))
            )

        oi_score = self._clamp(
            oi_change.get("positive_oi_change_count", 0) * 2
        )

        strike_score = self._clamp(
            strike.get("directional_score", 0) + 50
        )

        expiry_score = self._clamp(
            expiry.get("directional_score", 0) + 50
        )

        vrp_rank = ((vrp.get("latest") or {}).get("rank") or 0) * 100

        overall = round(mean([
            buying,
            dark_pool,
            dealer_gamma,
            oi_score,
            strike_score,
            expiry_score,
            vrp_rank,
        ]), 2)

        greek_flow_score = 50.0 if greek_flow else 0.0
        spot_gamma_score = 50.0 if spot else 0.0
        lit_flow_score = 50.0 if lit else 0.0
        market_tide_score = 50.0 if market_tide else 0.0
        sector_tide_score = 50.0 if sector_tide else 0.0
        ownership_score = 50.0 if ownership else 0.0
        short_score = 50.0 if shorts else 0.0
        insider_score = 50.0 if insiders else 0.0
        congress_score = 50.0 if congress else 0.0

        return {
            "symbol": symbol,
            "institutional_buying_score": round(buying,2),
            "institutional_selling_score": round(selling,2),
            "dark_pool_score": round(dark_pool,2),
            "dealer_gamma_score": round(dealer_gamma,2),
            "open_interest_score": round(oi_score,2),
            "strike_concentration_score": round(strike_score,2),
            "expiry_alignment_score": round(expiry_score,2),
            "variance_risk_score": round(vrp_rank,2),
            "overall_institutional_score": overall,
            "execution_impact": "OBSERVATION_ONLY",
            "status": "INSTITUTIONAL_INTELLIGENCE_READY",
        }
