from datetime import datetime

from app.services.simulation.greyline_simulation_decision_adapter import GreyLineSimulationDecisionAdapter


class BearMarketValidationSuiteEngine:
    """
    Validates whether GreyLine can produce PUT EXECUTE signals
    under known bearish component conditions.

    This does not change production scoring.
    It tests whether the current scoring framework is capable
    of elevating bearish opportunities when the evidence is bearish.
    """

    SCENARIOS = [
        {
            "name": "CONTROL_BULL_MARKET",
            "symbol": "QQQ",
            "close": 400,
            "components": {
                "market_data_score": 100,
                "liquidity_score": 90,
                "setup_score": 95,
                "bullish_setup_score": 95,
                "bearish_setup_score": 20,
                "regime_score": 90,
                "breadth_score": 90,
                "trend_persistence_score": 90,
                "institutional_sponsorship_score": 85,
                "asymmetry_score": 85,
                "volatility_score": 60,
                "risk_state_score": 85,
            },
        },
        {
            "name": "ORDERLY_BEAR_TREND",
            "symbol": "QQQ",
            "close": 350,
            "components": {
                "market_data_score": 100,
                "liquidity_score": 90,
                "setup_score": 25,
                "bullish_setup_score": 25,
                "bearish_setup_score": 90,
                "regime_score": 25,
                "breadth_score": 25,
                "trend_persistence_score": 20,
                "institutional_sponsorship_score": 30,
                "asymmetry_score": 25,
                "volatility_score": 75,
                "risk_state_score": 80,
            },
        },
        {
            "name": "PANIC_SELL_OFF",
            "symbol": "SPY",
            "close": 300,
            "components": {
                "market_data_score": 100,
                "liquidity_score": 95,
                "setup_score": 15,
                "bullish_setup_score": 15,
                "bearish_setup_score": 100,
                "regime_score": 15,
                "breadth_score": 10,
                "trend_persistence_score": 10,
                "institutional_sponsorship_score": 20,
                "asymmetry_score": 15,
                "volatility_score": 95,
                "risk_state_score": 70,
            },
        },
        {
            "name": "SECTOR_BEARISH_FINANCIALS",
            "symbol": "XLF",
            "close": 30,
            "components": {
                "market_data_score": 100,
                "liquidity_score": 90,
                "setup_score": 20,
                "bullish_setup_score": 20,
                "bearish_setup_score": 95,
                "regime_score": 20,
                "breadth_score": 35,
                "trend_persistence_score": 20,
                "institutional_sponsorship_score": 35,
                "asymmetry_score": 30,
                "volatility_score": 85,
                "risk_state_score": 80,
            },
        },
        {
            "name": "MIXED_MARKET_WEAK_PUT",
            "symbol": "XLU",
            "close": 70,
            "components": {
                "market_data_score": 100,
                "liquidity_score": 90,
                "setup_score": 40,
                "bullish_setup_score": 40,
                "bearish_setup_score": 70,
                "regime_score": 50,
                "breadth_score": 55,
                "trend_persistence_score": 45,
                "institutional_sponsorship_score": 50,
                "asymmetry_score": 45,
                "volatility_score": 60,
                "risk_state_score": 85,
            },
        },
    ]

    def run(self):
        results = []

        for scenario in self.SCENARIOS:
            result = GreyLineSimulationDecisionAdapter().evaluate(
                market_data={
                    "symbol": scenario["symbol"],
                    "close": scenario["close"],
                },
                component_overrides=scenario["components"],
            )

            results.append({
                "scenario": scenario["name"],
                "symbol": scenario["symbol"],
                "option_type": result.get("option_type"),
                "directional_bias": result.get("directional_bias"),
                "composite_score": result.get("composite_score"),
                "bullish_score": result.get("bullish_score"),
                "bearish_score": result.get("bearish_score"),
                "direction_confidence": result.get("direction_confidence"),
                "result": result.get("result"),
                "passed": self._passed(scenario["name"], result),
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "BearMarketValidationSuiteEngine",
            "scenario_count": len(results),
            "passed_count": len([x for x in results if x["passed"]]),
            "failed_count": len([x for x in results if not x["passed"]]),
            "results": results,
            "status": "BEAR_MARKET_VALIDATION_COMPLETE",
        }

    def _passed(self, name, result):
        if name == "CONTROL_BULL_MARKET":
            return result.get("option_type") == "CALL" and result.get("result") == "EXECUTE"

        if name in [
            "ORDERLY_BEAR_TREND",
            "PANIC_SELL_OFF",
            "SECTOR_BEARISH_FINANCIALS",
        ]:
            return result.get("option_type") == "PUT" and result.get("result") == "EXECUTE"

        if name == "MIXED_MARKET_WEAK_PUT":
            return result.get("option_type") == "PUT" and result.get("result") in ["WATCH", "EXECUTE"]

        return False
