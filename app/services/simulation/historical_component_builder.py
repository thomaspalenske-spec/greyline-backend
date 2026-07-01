class HistoricalComponentBuilder:
    """
    Simulator-only component builder.

    Purpose:
      Convert historical OHLCV snapshots into GreyLine-style component inputs.

    Rule:
      Simulator adapts to GreyLine.
      Production GreyLine engines are not modified for simulation.
    """

    def build(self, market_data):
        market_data = market_data or {}

        close = market_data.get("close")
        open_price = market_data.get("open")
        high = market_data.get("high")
        low = market_data.get("low")
        volume = market_data.get("volume")

        if not close or not open_price or not high or not low:
            return {
                "market_data_score": 0,
                "liquidity_score": 0,
                "setup_score": 0,
                "regime": {"regime": "NO_DATA", "regime_score": 0},
                "risk": {"risk_state": "NO_DATA", "risk_state_score": 0},
                "volatility_score": 0,
                "trend_persistence_score": 0,
                "breadth_score": 0,
                "institutional_sponsorship_score": 0,
                "asymmetry_score": 0,
            }

        history = market_data.get("history") or []
        closes = [float(r.get("close")) for r in history if r.get("close")]
        volumes = [float(r.get("volume")) for r in history if r.get("volume")]

        day_return_pct = ((close - open_price) / open_price) * 100
        intraday_range_pct = ((high - low) / close) * 100 if close else 0

        ret_5 = ((closes[-1] - closes[-5]) / closes[-5]) * 100 if len(closes) >= 5 and closes[-5] else day_return_pct
        ret_10 = ((closes[-1] - closes[-10]) / closes[-10]) * 100 if len(closes) >= 10 and closes[-10] else ret_5
        ret_20 = ((closes[-1] - closes[-20]) / closes[-20]) * 100 if len(closes) >= 20 and closes[-20] else ret_10

        close_location_pct = ((close - low) / (high - low)) * 100 if high != low else 50
        avg_volume_20 = sum(volumes[-20:]) / len(volumes[-20:]) if volumes[-20:] else volume
        volume_pressure = (volume / avg_volume_20) if avg_volume_20 else 1.0

        momentum_blend = (ret_5 * 0.50) + (ret_10 * 0.30) + (ret_20 * 0.20)
        downside_blend = -momentum_blend

        setup_score = min(100, max(0, 55 + momentum_blend * 5.0 + (close_location_pct - 50) * 0.18))
        bearish_setup_score = min(100, max(0, 55 + downside_blend * 5.0 + (50 - close_location_pct) * 0.18))

        volatility_score = min(100, max(0, 100 - intraday_range_pct * 8))
        trend_persistence_score = min(100, max(0, 55 + momentum_blend * 4.0))
        asymmetry_score = min(100, max(0, 55 + momentum_blend * 3.5 + min(10, max(-10, (volume_pressure - 1) * 20))))

        liquidity_score = 90 if volume and volume > 0 else 50

        regime_score = min(100, max(0, 55 + momentum_blend * 3.5))

        # Simulator-only risk model:
        # Do not treat all high range / high momentum days as automatically stressed.
        # Penalize true instability: wide range, downside close, weak close location.
        # Reward constructive upside closes and real liquidity.
        downside_penalty = abs(min(day_return_pct, 0)) * 6
        upside_credit = max(day_return_pct, 0) * 2
        liquidity_credit = 5 if volume and volume > 0 else -15

        risk_state_score = min(100, max(0,
            65
            - intraday_range_pct * 2.0
            - downside_penalty
            + upside_credit
            + (close_location_pct - 50) * 0.25
            + liquidity_credit
        ))

        breadth_score = min(100, max(0, 55 + momentum_blend * 2.8))
        institutional_sponsorship_score = min(100, max(0, 55 + momentum_blend * 3.0 + min(8, max(-8, (volume_pressure - 1) * 16))))

        if regime_score >= 65:
            regime = "STRONG_LIVE_TREND"
        elif regime_score >= 50:
            regime = "CONSTRUCTIVE_LIVE"
        elif regime_score >= 40:
            regime = "NEUTRAL"
        else:
            regime = "WEAK_LIVE"

        if risk_state_score >= 75:
            risk_state = "NORMAL"
        elif risk_state_score >= 60:
            risk_state = "ELEVATED"
        elif risk_state_score >= 45:
            risk_state = "DEFENSIVE"
        else:
            risk_state = "STRESSED"

        return {
            "market_data_score": 100,
            "liquidity_score": round(liquidity_score, 2),
            "setup_score": round(setup_score, 2),
            "bullish_setup_score": round(setup_score, 2),
            "bearish_setup_score": round(bearish_setup_score, 2),
            "regime": {
                "regime": regime,
                "regime_score": round(regime_score, 2),
            },
            "risk": {
                "risk_state": risk_state,
                "risk_state_score": round(risk_state_score, 2),
            },
            "volatility_score": round(volatility_score, 2),
            "trend_persistence_score": round(trend_persistence_score, 2),
            "breadth_score": round(breadth_score, 2),
            "institutional_sponsorship_score": round(institutional_sponsorship_score, 2),
            "asymmetry_score": round(asymmetry_score, 2),
        }
