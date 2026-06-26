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

        day_return_pct = ((close - open_price) / open_price) * 100
        intraday_range_pct = ((high - low) / close) * 100 if close else 0

        setup_score = min(100, max(0, 50 + day_return_pct * 10))
        volatility_score = min(100, max(0, 100 - intraday_range_pct * 8))
        trend_persistence_score = min(100, max(0, 50 + day_return_pct * 8))
        asymmetry_score = min(100, max(0, 50 + day_return_pct * 6))

        liquidity_score = 90 if volume and volume > 0 else 50

        regime_score = min(100, max(0, 50 + day_return_pct * 6))
        risk_state_score = min(100, max(0, 85 - intraday_range_pct * 5))
        breadth_score = min(100, max(0, 50 + day_return_pct * 4))
        institutional_sponsorship_score = min(100, max(0, 50 + day_return_pct * 5))

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
