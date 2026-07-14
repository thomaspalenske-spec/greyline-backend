import math
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

    @staticmethod
    def _activity_intensity(value, reference):
        """
        Bounded [0,100] magnitude gauge — NOT directional. tanh-shaped so it rises
        smoothly with activity and never hard-pins at the ceiling (the old
        premium/1e9*25 scaling pinned near 0 for anything under a few $B). `reference`
        is the premium level treated as 'notably active'. This is a within-name relative
        activity gauge, not a cross-name absolute (UW returns only the most-recent ~500
        prints, so absolute dollars are truncated and non-comparable across tickers).
        """
        ref = float(reference) or 1.0
        v = max(0.0, float(value or 0))
        return round(100.0 * math.tanh(v / ref), 2)

    @staticmethod
    def _directional_score(rows, field):
        """
        0-100 directional score from a signed flow field: net directional imbalance
        mapped around 50 (all-bullish -> 100, all-bearish -> 0, balanced/no-data -> 50).
        Replaces the old binary 50/0 "data present?" flags for real flow signals.
        """
        if not rows:
            return 50.0
        net = 0.0
        total = 0.0
        for row in rows:
            try:
                v = float(row.get(field) or 0)
            except (TypeError, ValueError):
                v = 0.0
            net += v
            total += abs(v)
        if total <= 0:
            return 50.0
        return max(0.0, min(100.0, 50 + 50 * (net / total)))

    @staticmethod
    def _signed_premium_score(rows):
        """
        0-100 directional score from lit/dark prints: premium executed at/above the
        NBBO midpoint counts bullish, below counts bearish; net premium imbalance
        mapped around 50. No prints -> 50.
        """
        if not rows:
            return 50.0
        net = 0.0
        total = 0.0
        for row in rows:
            try:
                price = float(row.get("price") or 0)
                prem = float(row.get("premium") or 0)
                bid = float(row.get("nbbo_bid") or 0)
                ask = float(row.get("nbbo_ask") or 0)
            except (TypeError, ValueError):
                continue
            if prem <= 0 or price <= 0:
                continue
            mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else price
            net += prem if price >= mid else -prem
            total += prem
        if total <= 0:
            return 50.0
        return max(0.0, min(100.0, 50 + 50 * (net / total)))

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

        # Bounded directional signal: the old formula was unbounded and pinned buying to
        # 100 (selling 0) for any strong-flow symbol, losing all granularity. Scale the
        # strike-weighted-2x-vs-flow signal into [-50, +50] so buying stays granular in
        # [0, 100]. Direction is preserved (bullish stays bullish); only magnitude changes.
        _dir_signal = (
            float(strike.get("directional_score") or 0)
            + float(options_flow.get("directional_score") or 0) / 2
        ) / 3.0
        buying = self._clamp(50 + _dir_signal)
        selling = self._clamp(50 - _dir_signal)

        # Dark-pool premium is a NON-DIRECTIONAL activity/conviction gauge: the aggregate
        # carries no aggressor side (can't tell buy vs sell), and the dollar total is
        # truncated to the most-recent ~500 prints. Bounded tanh intensity — reported for
        # context, but EXCLUDED from the directional composite below so a low value can't
        # masquerade as bearish (the old scaling pinned it near 0 and dragged the mean down).
        dark_pool = self._activity_intensity(
            float(dark.get("total_premium") or 0), 200_000_000
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

        # Real directional scores from the signed flow fields (was binary 50/0).
        greek_flow_score = self._directional_score(greek_flow, "dir_delta_flow")
        spot_gamma_score = self._directional_score(spot, "gamma_per_one_percent_move_dir")
        lit_flow_score = self._signed_premium_score(lit)
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

        # DIRECTIONAL institutional composite = the mission signal (inflow vs outflow).
        # Only feeds that carry a bullish/bearish sign are averaged. The five NON-directional
        # feeds are deliberately excluded so they can't inject false direction or pin the
        # composite via saturation:
        #   dark_pool     -> activity magnitude (no aggressor side)
        #   dealer_gamma  -> volatility regime (long/short gamma), not up/down
        #   spot_gamma    -> volatility regime; was saturating to 100
        #   oi_score      -> open-interest activity count; was saturating to 100
        #   vrp_rank      -> variance-risk-premium level, not direction
        # They remain reported below (non_directional_context) as conviction/regime context.
        directional_components = [
            buying,
            strike_score,
            expiry_score,
            greek_flow_score,
            lit_flow_score,
            market_tide_score,
            sector_tide_score,
            ownership_score,
            short_score,
            insider_score,
            congress_score,
        ]
        overall = round(mean(directional_components), 2)

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
            "overall_score_basis": "DIRECTIONAL_FEEDS_ONLY",
            "directional_component_count": len(directional_components),
            "non_directional_context": {
                "dark_pool_intensity": round(dark_pool, 2),
                "dealer_gamma_regime": round(dealer_gamma, 2),
                "spot_gamma_regime": round(spot_gamma_score, 2),
                "open_interest_activity": round(oi_score, 2),
                "variance_risk_level": round(vrp_rank, 2),
                "note": (
                    "Magnitude / volatility-regime signals — conviction & regime context, "
                    "not directional. Excluded from overall_institutional_score."
                ),
            },
            "execution_impact": "OBSERVATION_ONLY",
            "status": "INSTITUTIONAL_INTELLIGENCE_READY",
        }
