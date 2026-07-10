from statistics import mean

from app.services.unusual_whales_operational_environment_engine import (
    UnusualWhalesOperationalEnvironmentEngine,
)


class InstitutionalIntelligenceEngine:

    def __init__(self):
        self.uw = UnusualWhalesOperationalEnvironmentEngine()

    @staticmethod
    def _clamp(value, lo=0.0, hi=100.0):
        return max(lo, min(hi, float(value)))

    @staticmethod
    def _rows(value):
        if isinstance(value, dict):
            data = value.get("data")
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
            return [value]

        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

        return []

    def analyze(self, symbol: str):
        data = self.uw.analyze(symbol)

        if not isinstance(data, dict):
            return {
                "symbol": (symbol or "").upper().strip(),
                "execution_impact": "OBSERVATION_ONLY",
                "status": "INSTITUTIONAL_INTELLIGENCE_UNAVAILABLE",
            }

        options_flow = data.get("options_flow") or {}
        strike = data.get("flow_by_strike") or {}
        expiry = data.get("flow_by_expiry") or {}
        dark = data.get("symbol_dark_pool") or {}
        greek = data.get("greek_exposure") or {}
        oi_change = data.get("open_interest_change") or {}
        vrp = data.get("variance_risk_premium") or {}

        greek_flow = self._rows(data.get("greek_flow"))
        spot = self._rows(data.get("spot_exposures"))
        lit = self._rows(data.get("lit_flow"))
        market_tide = self._rows(data.get("market_tide"))
        sector_tide = self._rows(data.get("sector_tide"))
        ownership = self._rows(data.get("institutional_ownership"))
        shorts = self._rows(data.get("short_volume"))
        insiders = self._rows(data.get("insider_transactions"))
        congress = self._rows(data.get("congress_trades"))

        buying = self._clamp(
            50
            + float(strike.get("directional_score") or 0)
            + float(options_flow.get("directional_score") or 0) / 2
        )

        selling = self._clamp(
            50
            - float(strike.get("directional_score") or 0)
            - float(options_flow.get("directional_score") or 0) / 2
        )

        dark_pool = self._clamp(
            (float(dark.get("total_premium") or 0) / 1_000_000_000) * 25
        )

        dealer_gamma = 50.0
        latest_greek = greek.get("latest") or {}
        net_gamma = latest_greek.get("net_gamma")

        if net_gamma is not None:
            dealer_gamma = self._clamp(
                50 + max(-50, min(50, float(net_gamma) / 100000))
            )

        oi_score = self._clamp(
            float(oi_change.get("positive_oi_change_count") or 0) * 2
        )

        strike_score = self._clamp(
            float(strike.get("directional_score") or 0) + 50
        )

        expiry_score = self._clamp(
            float(expiry.get("directional_score") or 0) + 50
        )

        vrp_rank = self._clamp(
            float((vrp.get("latest") or {}).get("rank") or 0) * 100
        )

        greek_flow_score = 50.0 if greek_flow else 0.0
        spot_gamma_score = 50.0 if spot else 0.0
        lit_flow_score = 50.0 if lit else 0.0
        market_tide_score = 50.0
        if market_tide:
            latest_tide = market_tide[-1]
            call_premium = float(
                latest_tide.get("net_call_premium") or 0
            )
            put_premium = float(
                latest_tide.get("net_put_premium") or 0
            )
            gross_premium = abs(call_premium) + abs(put_premium)

            if gross_premium > 0:
                market_tide_score = self._clamp(
                    50
                    + (
                        (call_premium + put_premium)
                        / gross_premium
                    )
                    * 50
                )

        sector_tide_score = 50.0
        if sector_tide:
            latest_sector = sector_tide[-1]
            call_premium = float(
                latest_sector.get("net_call_premium") or 0
            )
            put_premium = float(
                latest_sector.get("net_put_premium") or 0
            )
            gross_premium = abs(call_premium) + abs(put_premium)

            if gross_premium > 0:
                sector_tide_score = self._clamp(
                    50
                    + (
                        (call_premium + put_premium)
                        / gross_premium
                    )
                    * 50
                )

        ownership_score = 50.0
        if ownership:
            positive_units = 0.0
            negative_units = 0.0

            for row in ownership:
                change = float(row.get("units_changed") or 0)

                if change > 0:
                    positive_units += change
                elif change < 0:
                    negative_units += abs(change)

            total_changed = positive_units + negative_units

            if total_changed > 0:
                ownership_score = self._clamp(
                    50
                    + (
                        (positive_units - negative_units)
                        / total_changed
                    )
                    * 50
                )

        raw_short = data.get("short_volume") or {}
        short_rows = []

        if isinstance(raw_short, dict):
            short_rows = [
                row
                for row in (raw_short.get("si") or [])
                if isinstance(row, dict)
            ]

        short_score = 50.0
        recent_short_rows = short_rows[:5]

        if recent_short_rows:
            ratios = [
                float(row.get("short_volume_ratio") or 0)
                for row in recent_short_rows
            ]
            average_short_ratio = sum(ratios) / len(ratios)

            short_score = self._clamp(
                50 + (0.50 - average_short_ratio) * 100
            )

        insider_score = 50.0
        if insiders:
            insider_buys = 0
            insider_sells = 0

            for row in insiders:
                transaction_type = str(
                    row.get("transaction_type")
                    or row.get("txn_type")
                    or row.get("type")
                    or ""
                ).lower()

                if "buy" in transaction_type or "purchase" in transaction_type:
                    insider_buys += 1
                elif "sell" in transaction_type or "sale" in transaction_type:
                    insider_sells += 1

            insider_total = insider_buys + insider_sells

            if insider_total > 0:
                insider_score = self._clamp(
                    50
                    + (
                        (insider_buys - insider_sells)
                        / insider_total
                    )
                    * 50
                )

        congress_score = 50.0
        symbol_upper = (symbol or "").upper().strip()

        symbol_congress = [
            row
            for row in congress
            if str(row.get("ticker") or "").upper() == symbol_upper
        ]

        if symbol_congress:
            congress_buys = 0
            congress_sells = 0

            for row in symbol_congress:
                transaction_type = str(
                    row.get("txn_type")
                    or row.get("transaction_type")
                    or ""
                ).lower()

                if "buy" in transaction_type or "purchase" in transaction_type:
                    congress_buys += 1
                elif "sell" in transaction_type or "sale" in transaction_type:
                    congress_sells += 1

            congress_total = congress_buys + congress_sells

            if congress_total > 0:
                congress_score = self._clamp(
                    50
                    + (
                        (congress_buys - congress_sells)
                        / congress_total
                    )
                    * 50
                )

        overall = round(mean([
            buying,
            dark_pool,
            dealer_gamma,
            oi_score,
            strike_score,
            expiry_score,
            vrp_rank,
            greek_flow_score,
            spot_gamma_score,
            lit_flow_score,
            market_tide_score,
            sector_tide_score,
            ownership_score,
            short_score,
            insider_score,
            congress_score,
        ]), 2)

        return {
            "symbol": (symbol or "").upper().strip(),
            "institutional_buying_score": round(buying, 2),
            "institutional_selling_score": round(selling, 2),
            "dark_pool_score": round(dark_pool, 2),
            "dealer_gamma_score": round(dealer_gamma, 2),
            "open_interest_score": round(oi_score, 2),
            "strike_concentration_score": round(strike_score, 2),
            "expiry_alignment_score": round(expiry_score, 2),
            "variance_risk_score": round(vrp_rank, 2),
            "greek_flow_score": round(greek_flow_score, 2),
            "spot_gamma_score": round(spot_gamma_score, 2),
            "lit_flow_score": round(lit_flow_score, 2),
            "market_tide_score": round(market_tide_score, 2),
            "sector_tide_score": round(sector_tide_score, 2),
            "ownership_score": round(ownership_score, 2),
            "short_interest_score": round(short_score, 2),
            "insider_score": round(insider_score, 2),
            "congress_score": round(congress_score, 2),
            "overall_institutional_score": overall,
            "execution_impact": "OBSERVATION_ONLY",
            "status": "INSTITUTIONAL_INTELLIGENCE_READY",
        }
