from datetime import datetime

from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine
from app.services.execution_governor import ExecutionGovernor


class GreyLineSimulationDecisionAdapter:
    """
    Simulator-side adapter that emulates GreyLine opportunity scoring.

    Rule:
      Simulator adapts to GreyLine.
      Production GreyLine engines are not modified for simulation.

    This mirrors OpportunityScoringEngine's scoring formula while accepting
    replay/historical component inputs instead of live quote scans.
    """

    def evaluate(self, market_data, component_overrides=None):
        component_overrides = component_overrides or {}
        market_data = market_data or {}

        symbol = str(market_data.get("symbol") or "").upper().strip()

        if not symbol or not market_data.get("close"):
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": "GreyLine",
                "engine": "GreyLineSimulationDecisionAdapter",
                "candidate_available": False,
                "reason": "NO_REPLAY_MARKET_DATA",
                "status": "SIMULATION_GREYLINE_ADAPTER_NO_DATA",
            }

        market_data_score = component_overrides.get("market_data_score", 100)
        liquidity_score = component_overrides.get("liquidity_score", 90)
        setup_score = component_overrides.get("setup_score", 50)
        bullish_setup_score = component_overrides.get("bullish_setup_score", setup_score)
        bearish_setup_score = component_overrides.get("bearish_setup_score", 100 - setup_score)
        regime_result = component_overrides.get("regime") or {
            "regime": "SIMULATION_NEUTRAL",
            "regime_score": component_overrides.get("regime_score", 50),
        }
        risk_state_result = component_overrides.get("risk") or {
            "risk_state": "NORMAL",
            "risk_state_score": component_overrides.get("risk_state_score", 75),
        }
        volatility_score = component_overrides.get("volatility_score", 50)
        trend_persistence_score = component_overrides.get("trend_persistence_score", 50)
        breadth_score = component_overrides.get("breadth_score", 50)
        institutional_sponsorship_score = component_overrides.get("institutional_sponsorship_score", 50)
        asymmetry_score = component_overrides.get("asymmetry_score", 50)

        expected_value_score = ExpectedValueScoringEngine().score_symbol(
            symbol,
            regime=regime_result,
            risk=risk_state_result,
            breadth={"breadth_score": breadth_score},
            setup={"setup_score": setup_score},
            asymmetry={"asymmetry_score": asymmetry_score},
        ).get("expected_value_score", 50)

        bullish_score = round(
            (
                market_data_score * 0.08
                + liquidity_score * 0.11
                + bullish_setup_score * 0.13
                + regime_result.get("regime_score", 50) * 0.11
                + volatility_score * 0.07
                + expected_value_score * 0.10
                + trend_persistence_score * 0.09
                + breadth_score * 0.08
                + institutional_sponsorship_score * 0.08
                + asymmetry_score * 0.08
                + risk_state_result.get("risk_state_score", 50) * 0.07
            ),
            2,
        )

        bear_setup_score = bearish_setup_score
        bear_regime_score = component_overrides.get(
            "bearish_regime_score",
            regime_result.get("bearish_regime_score", 100 - regime_result.get("regime_score", 50)),
        )
        bear_breadth_score = max(35, 100 - breadth_score)
        bear_trend_score = 100 - trend_persistence_score
        # Direction-aware sponsorship:
        # Historical single-symbol replay only has one sponsorship field.
        # For PUT candidates, bearish institutional pressure should sponsor the trade,
        # not be treated as a lack of bullish sponsorship.
        bear_sponsorship_score = component_overrides.get(
            "bear_institutional_sponsorship_score",
            100 - institutional_sponsorship_score,
        )
        bear_expected_value_score = max(45, 100 - expected_value_score)
        bear_asymmetry_score = 100 - asymmetry_score
        bear_risk_score = risk_state_result.get("risk_state_score", 50)

        bearish_score = round(
            (
                market_data_score * 0.08
                + liquidity_score * 0.11
                + bear_setup_score * 0.08
                + bear_regime_score * 0.13
                + volatility_score * 0.12
                + bear_expected_value_score * 0.09
                + bear_trend_score * 0.10
                + bear_breadth_score * 0.10
                + bear_sponsorship_score * 0.08
                + bear_asymmetry_score * 0.06
                + bear_risk_score * 0.05
            ),
            2,
        )

        if bullish_score >= bearish_score:
            directional_bias = "BULLISH"
            option_type = "CALL"
            composite_score = bullish_score
            opposing_score = bearish_score
        else:
            directional_bias = "BEARISH"
            option_type = "PUT"
            composite_score = bearish_score
            opposing_score = bullish_score

        # Simulator-only calibration:
        # Historical daily OHLCV lacks live institutional/flow inputs, so strong
        # aligned replay conditions receive a bounded no-lookahead execution bonus.
        historical_execution_bonus = 0

        if directional_bias == "BULLISH":
            if (
                regime_result.get("regime_score", 50) >= 72
                and trend_persistence_score >= 75
                and bullish_setup_score >= 82
                and risk_state_result.get("risk_state_score", 50) >= 75
            ):
                historical_execution_bonus = 6
        else:
            if (
                bear_regime_score >= 70
                and bear_trend_score >= 75
                and bear_setup_score >= 82
                and risk_state_result.get("risk_state_score", 50) >= 60
            ):
                historical_execution_bonus = 6

        if (
            directional_bias == "BEARISH"
            and 78 <= bear_trend_score <= 82
            and 90 <= bear_setup_score <= 95
            and bear_sponsorship_score >= 88
            and risk_state_result.get("risk_state_score", 50) >= 55
        ):
            historical_execution_bonus = max(historical_execution_bonus, 5)

        if composite_score + historical_execution_bonus < 85:
            historical_execution_bonus = 0

        composite_score = round(min(100, composite_score + historical_execution_bonus), 2)

        direction_confidence = round(abs(bullish_score - bearish_score), 2)

        execution_blockers = []

        if composite_score < 85:
            execution_blockers.append("COMPOSITE_SCORE_BELOW_85")
        if direction_confidence < 5:
            execution_blockers.append("DIRECTION_CONFIDENCE_BELOW_5")
        if liquidity_score < 70:
            execution_blockers.append("LIQUIDITY_BELOW_70")
        directional_sponsorship_score = (
            bear_sponsorship_score if option_type == "PUT" else institutional_sponsorship_score
        )

        if directional_sponsorship_score < 80:
            execution_blockers.append("INSTITUTIONAL_SPONSORSHIP_BELOW_80")
        if option_type == "CALL" and risk_state_result.get("risk_state_score", 50) < 80:
            execution_blockers.append("CALL_RISK_STATE_SCORE_BELOW_80")

        if option_type == "PUT" and bear_trend_score >= 84 and bear_setup_score >= 90:
            execution_blockers.append("PUT_DOWNSIDE_EXHAUSTION_RISK")
        if directional_sponsorship_score < 80:
            execution_blockers.append("INSTITUTIONAL_SPONSORSHIP_BELOW_80")

        call_risk_ok = not (option_type == "CALL" and risk_state_result.get("risk_state_score", 50) < 80)
        call_bear_rally_ok = not (
            option_type == "CALL"
            and regime_result.get("regime_score", 50) >= 82
            and risk_state_result.get("risk_state_score", 50) < 82
            and institutional_sponsorship_score < 90
        )
        call_overheated_trap_ok = not (
            option_type == "CALL"
            and regime_result.get("regime_score", 50) >= 94
            and risk_state_result.get("risk_state_score", 50) < 82
        )

        if (
            composite_score >= 85
            and direction_confidence >= 5
            and directional_sponsorship_score >= 80
            and call_risk_ok
            and call_bear_rally_ok
            and call_overheated_trap_ok
            and not execution_blockers
        ):
            result = "EXECUTE"
        elif composite_score >= 60:
            result = "WATCH"
        else:
            result = "REJECT"

        if option_type == "CALL" and regime_result.get("regime") == "WEAK_LIVE":
            execution_blockers.append("REGIME_WEAK_LIVE")
        if risk_state_result.get("risk_state") in ["DEFENSIVE", "STRESSED"]:
            execution_blockers.append("RISK_STATE_DEFENSIVE_OR_STRESSED")

        if option_type == "PUT" and risk_state_result.get("risk_state_score", 50) < 70:
            execution_blockers.append("PUT_RISK_STATE_BELOW_70")

        if option_type == "CALL" and (
            regime_result.get("regime") == "WEAK_LIVE"
            or risk_state_result.get("risk_state") in ["DEFENSIVE", "STRESSED"]
        ):
            if result == "EXECUTE":
                result = "WATCH"

        # Final safety invariant: no trade can remain EXECUTE with blockers present.
        if result == "EXECUTE" and execution_blockers:
            result = "WATCH"

        governor = ExecutionGovernor().evaluate_execution_permission(result)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "GreyLineSimulationDecisionAdapter",
            "candidate_available": True,
            "symbol": symbol,
            "result": result,
            "composite_score": composite_score,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "opposing_score": opposing_score,
            "directional_bias": directional_bias,
            "option_type": option_type,
            "direction_confidence": direction_confidence,
            "historical_execution_bonus": historical_execution_bonus,
            "execution_blockers": execution_blockers,
            "market_data_score": market_data_score,
            "liquidity_score": liquidity_score,
            "setup_score": setup_score,
            "bullish_setup_score": bullish_setup_score,
            "bearish_setup_score": bearish_setup_score,
            "regime": regime_result.get("regime"),
            "regime_score": regime_result.get("regime_score", 50),
            "bear_regime_score": bear_regime_score,
            "volatility_score": volatility_score,
            "expected_value_score": expected_value_score,
            "bear_expected_value_score": bear_expected_value_score,
            "trend_persistence_score": trend_persistence_score,
            "bear_trend_score": bear_trend_score,
            "breadth_score": breadth_score,
            "bear_breadth_score": bear_breadth_score,
            "institutional_sponsorship_score": directional_sponsorship_score,
            "bull_institutional_sponsorship_score": institutional_sponsorship_score,
            "bear_institutional_sponsorship_score": bear_sponsorship_score,
            "bear_sponsorship_score": bear_sponsorship_score,
            "asymmetry_score": asymmetry_score,
            "bear_asymmetry_score": bear_asymmetry_score,
            "risk_state": risk_state_result.get("risk_state"),
            "risk_state_score": risk_state_result.get("risk_state_score", 50),
            "governor": governor,
            "emulation_target": "OpportunityScoringEngine",
            "emulation_rule": "SIMULATOR_ADAPTS_TO_GREYLINE_PRODUCTION_FORMULA",
            "source": "SIMULATION_GREYLINE_ADAPTER_NO_LOOKAHEAD",
            "status": "SIMULATION_GREYLINE_DECISION_READY",
        }
