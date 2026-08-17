from datetime import datetime

from app.services.live_universe_quote_scanner import LiveUniverseQuoteScanner
from app.services.liquidity_scoring_engine import LiquidityScoringEngine
from app.services.setup_scoring_engine import SetupScoringEngine
from app.services.execution_governor import ExecutionGovernor
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.volatility_scoring_engine import VolatilityScoringEngine
from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine
from app.services.trend_persistence_scoring_engine import TrendPersistenceScoringEngine
from app.services.breadth_scoring_engine import BreadthScoringEngine
from app.services.institutional_sponsorship_scoring_engine import InstitutionalSponsorshipScoringEngine
from app.services.equity_institutional_flow_engine import EquityInstitutionalFlowEngine
from app.services.institutional_conviction_engine import InstitutionalConvictionEngine
from app.services.institutional_flow_momentum_engine import InstitutionalFlowMomentumEngine
from app.services.asymmetry_scoring_engine import AsymmetryScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine
from app.services.institutional.institutional_execution_gate_engine import InstitutionalExecutionGateEngine
from app.services.institutional.adaptive_institutional_weight_engine import (
    AdaptiveInstitutionalWeightEngine,
)
from app.services.regime_calibration_engine import (
    RegimeCalibrationEngine,
)
from app.services.institutional.institutional_attribution_engine import InstitutionalAttributionEngine
from app.services.institutional_intelligence_engine import (
    InstitutionalIntelligenceEngine,
)
from app.services.institutional.institutional_memory_engine import (
    InstitutionalMemoryEngine,
)
from app.services.decision_shadow_log_engine import DecisionShadowLogEngine
from app.services.institutional.institutional_validation_engine import (
    InstitutionalValidationEngine,
)
from app.services.institutional.institutional_forecast_engine import (
    InstitutionalForecastEngine,
)
from app.services.institutional.institutional_forecast_verification_engine import (
    InstitutionalForecastVerificationEngine,
)
from app.services.institutional.institutional_model_status_engine import (
    InstitutionalModelStatusEngine,
)
from app.services.unusual_whales_budget_governor import (
    UnusualWhalesBudgetGovernor,
)
from app.services.unusual_whales_refresh_decision_engine import (
    UnusualWhalesRefreshDecisionEngine,
)
from app.services.forecast_auto_tuning_engine import ForecastAutoTuningEngine


class OpportunityScoringEngine:

    def score_opportunities(self, limit=None):
        scoring_started_at = datetime.utcnow()
        timings = {
            "per_symbol": []
        }

        forecast_weights = (
            ForecastAutoTuningEngine()
            .evaluate()
            .get("weights", {})
        )

        t0 = datetime.utcnow()
        quote_scan = LiveUniverseQuoteScanner().scan_safe_subset()
        t1 = datetime.utcnow()
        timings["quote_scan_seconds"] = round((t1 - t0).total_seconds(), 2)

        opportunities = []
        symbols = quote_scan.get("symbols", [])
        if limit is not None:
            symbols = symbols[:limit]

        for item in symbols:
            symbol_started_at = datetime.utcnow()
            symbol_timings = {}

            symbol = item.get("symbol")
            quote_status = item.get("quote_status")
            http_status = item.get("http_status")

            if http_status == 200 and quote_status == "QUOTE_READ_SUCCESS":
                market_data_score = 100
            elif http_status == 200:
                market_data_score = 75
            elif quote_status == "QUOTE_READ_FAILED":
                market_data_score = 25
            else:
                market_data_score = 0
            t0 = datetime.utcnow()
            liquidity_score = LiquidityScoringEngine().score_symbol(symbol).get('liquidity_score', 50)
            t1 = datetime.utcnow()
            symbol_timings["liquidity_seconds"] = round((t1 - t0).total_seconds(), 2)

            t0 = datetime.utcnow()
            setup_result = SetupScoringEngine().score_symbol(symbol)
            setup_score = setup_result.get("setup_score", 50)
            bullish_setup_score = setup_result.get("bullish_setup_score", setup_score)
            bearish_setup_score = setup_result.get("bearish_setup_score", 100 - setup_score)
            t1 = datetime.utcnow()
            symbol_timings["setup_seconds"] = round((t1 - t0).total_seconds(), 2)

            t0 = datetime.utcnow()
            regime_result = RegimeScoringEngine().score_symbol(symbol)
            t1 = datetime.utcnow()
            symbol_timings["regime_seconds"] = round((t1 - t0).total_seconds(), 2)
            regime_score = regime_result.get("regime_score", 50)
            bearish_regime_score = regime_result.get("bearish_regime_score", 100 - regime_score)

            t0 = datetime.utcnow()
            volatility_score = VolatilityScoringEngine().score_symbol(symbol).get("volatility_score", 50)
            t1 = datetime.utcnow()
            symbol_timings["volatility_seconds"] = round((t1 - t0).total_seconds(), 2)

            t0 = datetime.utcnow()
            trend_persistence_result = TrendPersistenceScoringEngine().score_symbol(symbol)
            trend_persistence_score = trend_persistence_result.get("trend_persistence_score", 50)
            bearish_trend_persistence_score = trend_persistence_result.get(
                "bearish_trend_persistence_score",
                max(35, 100 - trend_persistence_score),
            )
            t1 = datetime.utcnow()
            symbol_timings["trend_persistence_seconds"] = round((t1 - t0).total_seconds(), 2)

            t0 = datetime.utcnow()
            breadth_result = BreadthScoringEngine().score_symbol(symbol)
            breadth_score = breadth_result.get("breadth_score", 50)
            bearish_breadth_score = breadth_result.get(
                "bearish_breadth_score",
                max(35, 100 - breadth_score),
            )
            t1 = datetime.utcnow()
            symbol_timings["breadth_seconds"] = round((t1 - t0).total_seconds(), 2)

            t0 = datetime.utcnow()
            sponsorship_result = InstitutionalSponsorshipScoringEngine().score_symbol(symbol)
            institutional_sponsorship_score = sponsorship_result.get("institutional_sponsorship_score", 50)
            equity_flow_result = EquityInstitutionalFlowEngine().evaluate_symbol(symbol)
            institutional_inflow_score = equity_flow_result.get("institutional_inflow_score", institutional_sponsorship_score)
            institutional_outflow_score = equity_flow_result.get("institutional_outflow_score", 100 - institutional_sponsorship_score)
            t1 = datetime.utcnow()
            symbol_timings["institutional_sponsorship_seconds"] = round((t1 - t0).total_seconds(), 2)
            symbol_timings["equity_institutional_flow_seconds"] = symbol_timings["institutional_sponsorship_seconds"]

            t0 = datetime.utcnow()
            asymmetry_score = AsymmetryScoringEngine().score_symbol(symbol).get("asymmetry_score", 50)
            t1 = datetime.utcnow()
            symbol_timings["asymmetry_seconds"] = round((t1 - t0).total_seconds(), 2)

            t0 = datetime.utcnow()
            risk_state_result = RiskStateScoringEngine().score_symbol(symbol)
            t1 = datetime.utcnow()
            symbol_timings["risk_state_seconds"] = round((t1 - t0).total_seconds(), 2)
            risk_state_score = risk_state_result.get("risk_state_score", 50)

            t0 = datetime.utcnow()
            expected_value_result = ExpectedValueScoringEngine().score_symbol(
                symbol,
                regime=regime_result,
                risk=risk_state_result,
                breadth={"breadth_score": breadth_score},
                setup={
                    "setup_score": setup_score,
                    "bearish_setup_score": bearish_setup_score,
                },
                asymmetry={"asymmetry_score": asymmetry_score},
            )
            expected_value_score = expected_value_result.get("expected_value_score", 50)
            bearish_expected_value_score = expected_value_result.get(
                "bearish_expected_value_score",
                max(45, 100 - expected_value_score),
            )
            t1 = datetime.utcnow()
            symbol_timings["expected_value_seconds"] = round((t1 - t0).total_seconds(), 2)

            t0 = datetime.utcnow()
            bull_conviction = InstitutionalConvictionEngine().score(
                "CALL",
                setup_result,
                regime_result,
                trend_persistence_result,
                equity_flow_result,
                symbol=symbol,
            )
            bear_conviction = InstitutionalConvictionEngine().score(
                "PUT",
                setup_result,
                regime_result,
                trend_persistence_result,
                equity_flow_result,
                symbol=symbol,
            )
            institutional_conviction_score = bull_conviction.get("institutional_conviction_score", 50)
            bear_institutional_conviction_score = bear_conviction.get("institutional_conviction_score", 50)
            t1 = datetime.utcnow()
            symbol_timings["institutional_conviction_seconds"] = round((t1 - t0).total_seconds(), 2)

            adaptive_weight_engine = (
                AdaptiveInstitutionalWeightEngine()
            )

            bullish_adaptive_weighting = (
                adaptive_weight_engine.evaluate(
                    symbol,
                    "CALL",
                )
            )
            bullish_weights = (
                bullish_adaptive_weighting.get("weights")
                or AdaptiveInstitutionalWeightEngine.BULLISH_BASELINE
            )

            bullish_score = round(
                (
                    market_data_score
                    * bullish_weights["market_data"]
                    + liquidity_score
                    * bullish_weights["liquidity"]
                    + bullish_setup_score
                    * bullish_weights["setup"] * forecast_weights.get("setup_weight", 1.0)
                    + regime_score
                    * bullish_weights["regime"] * forecast_weights.get("regime_weight", 1.0)
                    + volatility_score
                    * bullish_weights["volatility"] * forecast_weights.get("volatility_weight", 1.0)
                    + expected_value_score
                    * bullish_weights["expected_value"]
                    + trend_persistence_score
                    * bullish_weights["trend"]
                    + breadth_score
                    * bullish_weights["breadth"] * forecast_weights.get("breadth_weight", 1.0)
                    + institutional_inflow_score
                    * bullish_weights["institutional_flow"]
                    + institutional_conviction_score
                    * bullish_weights[
                        "institutional_conviction"
                    ]
                    + asymmetry_score
                    * bullish_weights["asymmetry"] * forecast_weights.get("asymmetry_weight", 1.0)
                    + risk_state_score
                    * bullish_weights["risk"] * forecast_weights.get("risk_state_weight", 1.0)
                ),
                2,
            )

            # Directional mirror scores.
            # Bullish components reward strength; bearish components must reward weakness.
            bear_setup_score = bearish_setup_score
            bear_regime_score = bearish_regime_score
            # Do not let broad-market bullish breadth hard-zero valid sector/index PUT setups.
            # Strong bullish breadth should dampen bearish trades, not erase them.
            bear_breadth_score = max(35, bearish_breadth_score)
            bear_trend_score = bearish_trend_persistence_score
            bear_sponsorship_score = institutional_outflow_score
            # Keep bearish EV from being mechanically crushed by bullish EV mirror.
            bear_expected_value_score = bearish_expected_value_score
            bear_asymmetry_score = 100 - asymmetry_score
            bear_risk_score = risk_state_score

            bearish_adaptive_weighting = (
                adaptive_weight_engine.evaluate(
                    symbol,
                    "PUT",
                )
            )
            bearish_weights = (
                bearish_adaptive_weighting.get("weights")
                or AdaptiveInstitutionalWeightEngine.BEARISH_BASELINE
            )

            bearish_score = round(
                (
                    market_data_score
                    * bearish_weights["market_data"]
                    + liquidity_score
                    * bearish_weights["liquidity"]
                    + bear_setup_score
                    * bearish_weights["setup"] * forecast_weights.get("setup_weight", 1.0)
                    + bear_regime_score
                    * bearish_weights["regime"] * forecast_weights.get("regime_weight", 1.0)
                    + volatility_score
                    * bearish_weights["volatility"] * forecast_weights.get("volatility_weight", 1.0)
                    + bear_expected_value_score
                    * bearish_weights["expected_value"]
                    + bear_trend_score
                    * bearish_weights["trend"]
                    + bear_breadth_score
                    * bearish_weights["breadth"] * forecast_weights.get("breadth_weight", 1.0)
                    + bear_sponsorship_score
                    * bearish_weights["institutional_flow"]
                    + bear_institutional_conviction_score
                    * bearish_weights[
                        "institutional_conviction"
                    ]
                    + bear_asymmetry_score
                    * bearish_weights["asymmetry"] * forecast_weights.get("asymmetry_weight", 1.0)
                    + bear_risk_score
                    * bearish_weights["risk"] * forecast_weights.get("risk_state_weight", 1.0)
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

            direction_confidence = round(abs(bullish_score - bearish_score), 2)

            institutional_gate = InstitutionalExecutionGateEngine().evaluate(symbol)

            composite_score = round(
                composite_score *
                institutional_gate["institutional_multiplier"],
                2,
            )

            direction_confidence = round(
                direction_confidence +
                institutional_gate["confidence_adjustment"],
                2,
            )

            # Direction-aware regime: a bearish (PUT) candidate must be judged against the
            # BEARISH regime, not the bullish one. Judging puts by the bullish regime vetoed
            # every aligned bearish setup on weak/down days — the root cause of the
            # 2026-07-13 zero-trade session (all 3,929 EXECUTE-qualified puts demoted to WATCH
            # because the bullish tape read WEAK_LIVE, which for a put is the thesis).
            directional_regime_label = (
                regime_result.get("bearish_regime")
                if option_type == "PUT"
                else regime_result.get("regime")
            )
            directional_regime_weak = (
                directional_regime_label == "WEAK_BEARISH_LIVE"
                if option_type == "PUT"
                else directional_regime_label == "WEAK_LIVE"
            )

            current_regime_for_decision = (
                directional_regime_label or "UNKNOWN"
            )

            try:
                regime_calibration = (
                    RegimeCalibrationEngine().evaluate(
                        current_regime_for_decision
                    )
                )
            except Exception as exc:
                regime_calibration = {
                    "regime": current_regime_for_decision,
                    "sample_size": 0,
                    "actionable": False,
                    "confidence_adjustment": 0.0,
                    "composite_adjustment": 0.0,
                    "position_multiplier": 1.0,
                    "execution_allowed": True,
                    "state": "DEGRADED",
                    "execution_impact": "OBSERVATION_ONLY",
                    "error": repr(exc),
                    "status": "REGIME_CALIBRATION_DEGRADED",
                }

            direction_confidence = round(
                max(
                    0.0,
                    direction_confidence
                    + float(
                        regime_calibration.get(
                            "confidence_adjustment"
                        )
                        or 0.0
                    ),
                ),
                2,
            )

            composite_score = round(
                max(
                    0.0,
                    min(
                        100.0,
                        composite_score
                        + float(
                            regime_calibration.get(
                                "composite_adjustment"
                            )
                            or 0.0
                        ),
                    ),
                ),
                2,
            )

            regime_execution_allowed = bool(
                regime_calibration.get(
                    "execution_allowed",
                    True,
                )
            )

            if (
                institutional_gate["allow_execution"]
                and regime_execution_allowed
                and composite_score >= 85
                and direction_confidence >= 5
            ):
                result = "EXECUTE"
            elif composite_score >= 60:
                result = "WATCH"
            else:
                result = "REJECT"

            institutional_flow_direction = equity_flow_result.get("institutional_flow_direction")
            institutional_flow_aligned = (
                (option_type == "CALL" and institutional_flow_direction == "INFLOW")
                or (option_type == "PUT" and institutional_flow_direction == "OUTFLOW")
                or institutional_flow_direction == "NEUTRAL"
            )

            institutional_flow_gate = "ALIGNED"
            if not institutional_flow_aligned:
                institutional_flow_gate = "MISALIGNED_DOWNGRADED"
                if result == "EXECUTE":
                    result = "WATCH"

            momentum_input = {
                "symbol": symbol,
                "option_type": option_type,
                "result": result,
                "composite_score": composite_score,
                "institutional_flow_direction": institutional_flow_direction,
                "institutional_flow_confidence": equity_flow_result.get("institutional_flow_confidence"),
                "institutional_conviction_score": institutional_conviction_score if option_type == "CALL" else bear_institutional_conviction_score,
                "institutional_conviction": (
                    bull_conviction
                    if option_type == "CALL"
                    else bear_conviction
                ),
                "institutional_memory_actionable": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_actionable"
                    )
                ),
                "institutional_memory_score": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_score"
                    )
                ),
                "institutional_memory_direction": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_direction"
                    )
                ),
                "institutional_memory_execution_impact": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_execution_impact"
                    )
                ),
                "institutional_flow_gate": institutional_flow_gate,
            }
            institutional_flow_momentum = InstitutionalFlowMomentumEngine().update(momentum_input)

            if institutional_flow_momentum.get("institutional_flow_decay") is True and result == "EXECUTE":
                result = "WATCH"

            if (
                directional_regime_weak
                or risk_state_result.get("risk_state") in ["DEFENSIVE", "STRESSED"]
            ):
                if result == "EXECUTE":
                    result = "WATCH"

            t0 = datetime.utcnow()
            governor = ExecutionGovernor().evaluate_execution_permission(result)
            t1 = datetime.utcnow()
            symbol_timings["governor_seconds"] = round((t1 - t0).total_seconds(), 2)

            symbol_completed_at = datetime.utcnow()
            symbol_timings["symbol"] = symbol
            symbol_timings["total_symbol_seconds"] = round((symbol_completed_at - symbol_started_at).total_seconds(), 2)
            timings["per_symbol"].append(symbol_timings)

            current_regime = (
                regime_result.get("regime") or "UNKNOWN"
            )

            regime_trust = {
                "regime": current_regime,
                "sample_size": regime_calibration.get(
                    "sample_size"
                ),
                "bayesian_accuracy_pct": (
                    regime_calibration.get(
                        "bayesian_accuracy_pct"
                    )
                ),
                "credible_interval_95": (
                    regime_calibration.get(
                        "credible_interval_95"
                    )
                ),
                "actionable": regime_calibration.get(
                    "actionable",
                    False,
                ),
                "confidence_adjustment": (
                    regime_calibration.get(
                        "confidence_adjustment",
                        0.0,
                    )
                ),
                "composite_adjustment": (
                    regime_calibration.get(
                        "composite_adjustment",
                        0.0,
                    )
                ),
                "position_multiplier": (
                    regime_calibration.get(
                        "position_multiplier",
                        1.0,
                    )
                ),
                "execution_allowed": (
                    regime_calibration.get(
                        "execution_allowed",
                        True,
                    )
                ),
                "state": regime_calibration.get("state"),
                "execution_impact": (
                    regime_calibration.get(
                        "execution_impact"
                    )
                ),
                "status": regime_calibration.get(
                    "status"
                ),
            }

            candidate = {
                "symbol": symbol,
                "quote_status": quote_status,
                "market_data_score": market_data_score,
                "liquidity_score": liquidity_score,
                "setup_score": setup_score,
                "bullish_setup_score": bullish_setup_score,
                "bearish_setup_score": bearish_setup_score,
                "regime_score": regime_score,
                "bear_regime_score": bear_regime_score,
                "regime": regime_result.get("regime"),
                "bearish_regime": regime_result.get("bearish_regime"),
                "directional_regime": directional_regime_label,
                "directional_regime_weak": directional_regime_weak,
                "regime_calibration": regime_calibration,
                "regime_calibration_state": (
                    regime_calibration.get("state")
                ),
                "regime_calibration_actionable": (
                    regime_calibration.get("actionable")
                    is True
                ),
                "regime_position_multiplier": (
                    regime_calibration.get(
                        "position_multiplier",
                        1.0,
                    )
                ),
                "regime_execution_allowed": (
                    regime_calibration.get(
                        "execution_allowed",
                        True,
                    )
                ),
                "regime_composite_adjustment": (
                    regime_calibration.get(
                        "composite_adjustment",
                        0.0,
                    )
                ),
                "forecast_regime_trust": regime_trust,
                "forecast_regime_trust_actionable": (
                    regime_trust.get("actionable") is True
                ),
                "forecast_regime_trust_sample_size": (
                    regime_trust.get("sample_size")
                ),
                "forecast_regime_bayesian_accuracy_pct": (
                    regime_trust.get(
                        "bayesian_accuracy_pct"
                    )
                ),
                "forecast_regime_confidence_adjustment": (
                    regime_trust.get(
                        "confidence_adjustment"
                    )
                ),
                "forecast_regime_trust_impact": (
                    regime_trust.get("execution_impact")
                ),
                "regime_live_context": {
                    "last": regime_result.get("last"),
                    "previous_close": regime_result.get("previous_close"),
                    "vwap": regime_result.get("vwap"),
                    "net_change_pct": regime_result.get("net_change_pct"),
                    "volume": regime_result.get("volume"),
                    "previous_volume": regime_result.get("previous_volume"),
                },
                "volatility_score": volatility_score,
                "expected_value_score": expected_value_score,
                "bear_expected_value_score": bear_expected_value_score,
                "trend_persistence_score": trend_persistence_score,
                "bear_trend_score": bear_trend_score,
                "breadth_score": breadth_score,
                "bear_breadth_score": bear_breadth_score,
                "institutional_sponsorship_score": institutional_sponsorship_score,
                "institutional_inflow_score": institutional_inflow_score,
                "institutional_outflow_score": institutional_outflow_score,
                "net_institutional_flow_score": equity_flow_result.get("net_institutional_flow_score"),
                "institutional_flow_direction": equity_flow_result.get("institutional_flow_direction"),
                "institutional_flow_strength": equity_flow_result.get("institutional_flow_strength"),
                "institutional_flow_confidence": equity_flow_result.get("institutional_flow_confidence"),
                "institutional_flow_reasons": equity_flow_result.get("institutional_flow_reasons"),
                "institutional_flow_context": equity_flow_result.get("institutional_flow_context"),
                "institutional_flow_aligned": institutional_flow_aligned,
                "institutional_flow_gate": institutional_flow_gate,
                "institutional_conviction_score": institutional_conviction_score if option_type == "CALL" else bear_institutional_conviction_score,
                "institutional_conviction": (
                    bull_conviction
                    if option_type == "CALL"
                    else bear_conviction
                ),
                "institutional_memory_actionable": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_actionable"
                    )
                ),
                "institutional_memory_score": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_score"
                    )
                ),
                "institutional_memory_direction": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_direction"
                    )
                ),
                "institutional_memory_execution_impact": (
                    (
                        bull_conviction
                        if option_type == "CALL"
                        else bear_conviction
                    ).get(
                        "institutional_memory_execution_impact"
                    )
                ),
                "institutional_conviction_state": bull_conviction.get("institutional_conviction_state") if option_type == "CALL" else bear_conviction.get("institutional_conviction_state"),
                "institutional_conviction_reasons": bull_conviction.get("institutional_conviction_reasons") if option_type == "CALL" else bear_conviction.get("institutional_conviction_reasons"),
                "institutional_conviction_components": bull_conviction.get("institutional_conviction_components") if option_type == "CALL" else bear_conviction.get("institutional_conviction_components"),
                "institutional_flow_momentum_score": institutional_flow_momentum.get("institutional_flow_momentum_score"),
                "institutional_flow_acceleration": institutional_flow_momentum.get("institutional_flow_acceleration"),
                "institutional_flow_velocity": institutional_flow_momentum.get("institutional_flow_velocity"),
                "institutional_flow_trend": institutional_flow_momentum.get("institutional_flow_trend"),
                "institutional_flow_decay": institutional_flow_momentum.get("institutional_flow_decay"),
                "institutional_flow_duration": institutional_flow_momentum.get("institutional_flow_duration"),
                "institutional_flow_persistence": institutional_flow_momentum.get("institutional_flow_persistence"),
                "institutional_flow_momentum_context": institutional_flow_momentum.get("institutional_flow_momentum_context"),
                "bear_sponsorship_score": bear_sponsorship_score,
                "asymmetry_score": asymmetry_score,
                "bear_asymmetry_score": bear_asymmetry_score,
                "risk_state_score": risk_state_score,
                "risk_state": risk_state_result.get("risk_state"),
                "risk_live_context": {
                    "last": risk_state_result.get("last"),
                    "bid": risk_state_result.get("bid"),
                    "ask": risk_state_result.get("ask"),
                    "spread_pct": risk_state_result.get("spread_pct"),
                    "vwap": risk_state_result.get("vwap"),
                    "vwap_distance_pct": risk_state_result.get("vwap_distance_pct"),
                    "net_change_pct_abs": risk_state_result.get("net_change_pct_abs"),
                    "volume": risk_state_result.get("volume"),
                    "previous_volume": risk_state_result.get("previous_volume"),
                },
                "composite_score": composite_score,
                "bullish_score": bullish_score,
                "bearish_score": bearish_score,
                "opposing_score": opposing_score,
                "directional_bias": directional_bias,
                "option_type": option_type,
                "direction_confidence": direction_confidence,
                "institutional_execution_gate": institutional_gate,
                "institutional_model_status": (
                    InstitutionalModelStatusEngine()
                    .evaluate(symbol)
                ),
                "institutional_model_actionable": False,
                "institutional_model_execution_impact": (
                    "OBSERVATION_ONLY"
                ),
                "adaptive_institutional_weighting": (
                    bullish_adaptive_weighting
                    if option_type == "CALL"
                    else bearish_adaptive_weighting
                ),
                "bullish_adaptive_institutional_weighting": (
                    bullish_adaptive_weighting
                ),
                "bearish_adaptive_institutional_weighting": (
                    bearish_adaptive_weighting
                ),
                "result": result,
                "order_placement_allowed": governor.get("order_placement_allowed"),
                "governor_status": governor.get("status"),
                "execution_enabled": False
            }

            try:
                candidate["institutional_attribution"] = (
                    InstitutionalAttributionEngine().attribute(candidate)
                )
            except Exception as exc:
                candidate["institutional_attribution"] = {
                    "symbol": symbol,
                    "error": repr(exc),
                    "status": "INSTITUTIONAL_ATTRIBUTION_DEGRADED",
                }

            opportunities.append(candidate)

        # Enrich only the strongest live candidates with direct Unusual
        # Whales intelligence. Do not call all 23 endpoints for every
        # symbol, and do not alter execution scoring until validation
        # history is sufficient.
        t0 = datetime.utcnow()

        institutional_intelligence_symbols = []
        institutional_intelligence_errors = {}

        uw_budget_governor = UnusualWhalesBudgetGovernor()
        uw_budget_policy = uw_budget_governor.evaluate()

        eligible_for_intelligence = [
            candidate
            for candidate in opportunities
            if uw_budget_governor.allow_candidate(candidate)
        ]

        ranked_for_intelligence = sorted(
            eligible_for_intelligence,
            key=lambda row: float(
                row.get("composite_score") or 0
            ),
            reverse=True,
        )[:1]

        # Symbol -> its OWN last price from this cycle's quote scan. Looked up by ticker so
        # a stale loop variable can never again attribute one instrument's price to another.
        quote_price_by_symbol = {}
        for _row in (quote_scan.get("symbols") or []):
            _sym = _row.get("symbol")
            _last = _row.get("last")
            if _sym and isinstance(_last, (int, float)) and _last > 0:
                quote_price_by_symbol[_sym] = float(_last)

        intelligence_engine = InstitutionalIntelligenceEngine()
        memory_engine = InstitutionalMemoryEngine()
        validation_engine = InstitutionalValidationEngine()
        forecast_engine = InstitutionalForecastEngine()
        forecast_verification_engine = (
            InstitutionalForecastVerificationEngine()
        )
        refresh_engine = UnusualWhalesRefreshDecisionEngine()

        for candidate in ranked_for_intelligence:
            candidate_symbol = candidate.get("symbol")

            try:
                refresh_decision = refresh_engine.evaluate(
                    candidate,
                    uw_budget_policy,
                )

                candidate[
                    "unusual_whales_refresh_decision"
                ] = refresh_decision

                if not refresh_decision.get("refresh_allowed"):
                    latest_memory = memory_engine.latest(
                        candidate_symbol
                    )
                    cached_intelligence = (
                        (latest_memory or {}).get("snapshot")
                        or {}
                    )

                    if cached_intelligence:
                        candidate[
                            "direct_institutional_intelligence"
                        ] = cached_intelligence
                        candidate[
                            "overall_institutional_score"
                        ] = cached_intelligence.get(
                            "overall_institutional_score"
                        )
                        candidate[
                            "institutional_market_tide_score"
                        ] = cached_intelligence.get(
                            "market_tide_score"
                        )
                        candidate[
                            "institutional_sector_tide_score"
                        ] = cached_intelligence.get(
                            "sector_tide_score"
                        )
                        candidate[
                            "institutional_ownership_score"
                        ] = cached_intelligence.get(
                            "ownership_score"
                        )
                        candidate[
                            "institutional_short_interest_score"
                        ] = cached_intelligence.get(
                            "short_interest_score"
                        )
                        candidate[
                            "institutional_intelligence_execution_impact"
                        ] = "OBSERVATION_ONLY"
                        candidate[
                            "institutional_intelligence_status"
                        ] = (
                            "INSTITUTIONAL_INTELLIGENCE_MEMORY_REUSED"
                        )

                        validation = validation_engine.evaluate(
                            candidate_symbol
                        )
                        forecast = forecast_engine.evaluate(
                            candidate_symbol
                        )
                        forecast_verification = (
                            forecast_verification_engine.evaluate(
                                candidate_symbol
                            )
                        )

                        candidate[
                            "institutional_validation"
                        ] = validation
                        candidate[
                            "institutional_forecast_verification"
                        ] = forecast_verification
                        candidate[
                            "institutional_forecast"
                        ] = forecast
                        candidate[
                            "institutional_validation_ready"
                        ] = validation.get("validated") is True
                        candidate[
                            "institutional_forecast_available"
                        ] = (
                            forecast.get(
                                "forecast_available"
                            )
                            is True
                        )
                        candidate[
                            "institutional_forecast_trend"
                        ] = forecast.get(
                            "institutional_trend"
                        )
                        candidate[
                            "institutional_forecast_score"
                        ] = forecast.get(
                            "projected_score_next_snapshot"
                        )
                        candidate[
                            "institutional_forecast_confidence"
                        ] = forecast.get(
                            "forecast_confidence"
                        )
                        candidate[
                            "institutional_calibrated_forecast_confidence"
                        ] = forecast_verification.get(
                            "calibrated_forecast_confidence"
                        )
                        candidate[
                            "institutional_forecast_trust_state"
                        ] = forecast_verification.get(
                            "forecast_trust_state"
                        )

                        institutional_intelligence_symbols.append(
                            candidate_symbol
                        )

                    continue

                intelligence = intelligence_engine.analyze(
                    candidate_symbol
                )

                candidate["direct_institutional_intelligence"] = (
                    intelligence
                )
                candidate["overall_institutional_score"] = (
                    intelligence.get(
                        "overall_institutional_score"
                    )
                )
                candidate["institutional_market_tide_score"] = (
                    intelligence.get("market_tide_score")
                )
                candidate["institutional_sector_tide_score"] = (
                    intelligence.get("sector_tide_score")
                )
                candidate["institutional_ownership_score"] = (
                    intelligence.get("ownership_score")
                )
                candidate["institutional_short_interest_score"] = (
                    intelligence.get("short_interest_score")
                )
                candidate[
                    "institutional_intelligence_execution_impact"
                ] = intelligence.get("execution_impact")
                candidate["institutional_intelligence_status"] = (
                    intelligence.get("status")
                )

                memory_result = memory_engine.record(
                    candidate_symbol,
                    intelligence,
                    source="OPPORTUNITY_SCORING_ENGINE",
                    minimum_interval_seconds=300,
                    # Pass the price already fetched this cycle so the flow↔price
                    # co-record is deterministic instead of relying on a second live
                    # quote fetch that fails silently (root cause of ungradable snapshots).
                    #
                    # This read `item.get("last")` — but `item` is bound by
                    # `for item in symbols:` ~890 lines above and is long out of that loop,
                    # so it held ONE stale scan row: the last symbol processed. Every
                    # candidate's price point was therefore written with an unrelated
                    # instrument's price under its own ticker. It is why every file in
                    # app/data/price_history bottoms out in the same 92-98 band whatever
                    # the symbol really trades at, and why a SPY forecast graded +87.6% "A"
                    # against a "current price" of 92.75. Every fixed-horizon grade,
                    # flow↔price join and outcome return built on that series was garbage.
                    price=quote_price_by_symbol.get(candidate_symbol),
                )

                # Shadow A/B: log momentum-proxy vs flow-implied direction (no effect
                # on the live decision) so we can grade which predicts better this session.
                DecisionShadowLogEngine().log(candidate_symbol, candidate, intelligence)

                refresh_engine.mark_refreshed(candidate)

                validation = validation_engine.evaluate(
                    candidate_symbol
                )
                forecast = forecast_engine.evaluate(
                    candidate_symbol
                )
                forecast_verification = (
                    forecast_verification_engine.evaluate(
                        candidate_symbol
                    )
                )

                candidate["institutional_memory"] = memory_result
                candidate[
                    "institutional_forecast_verification"
                ] = forecast_verification
                candidate["institutional_validation"] = validation
                candidate["institutional_forecast"] = forecast
                candidate["institutional_validation_ready"] = (
                    validation.get("validated") is True
                )
                candidate["institutional_forecast_available"] = (
                    forecast.get("forecast_available") is True
                )
                candidate["institutional_forecast_trend"] = (
                    forecast.get("institutional_trend")
                )
                candidate["institutional_forecast_score"] = (
                    forecast.get(
                        "projected_score_next_snapshot"
                    )
                )
                candidate["institutional_forecast_confidence"] = (
                    forecast.get("forecast_confidence")
                )
                candidate[
                    "institutional_calibrated_forecast_confidence"
                ] = forecast_verification.get(
                    "calibrated_forecast_confidence"
                )
                candidate[
                    "institutional_forecast_trust_state"
                ] = forecast_verification.get(
                    "forecast_trust_state"
                )

                institutional_intelligence_symbols.append(
                    candidate_symbol
                )

            except Exception as exc:
                candidate["direct_institutional_intelligence"] = None
                candidate["institutional_intelligence_status"] = (
                    "INSTITUTIONAL_INTELLIGENCE_DEGRADED"
                )
                institutional_intelligence_errors[
                    candidate_symbol
                ] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }

        t1 = datetime.utcnow()
        timings["institutional_intelligence_seconds"] = round(
            (t1 - t0).total_seconds(),
            2,
        )
        timings["institutional_intelligence_symbols"] = (
            institutional_intelligence_symbols
        )
        timings["institutional_intelligence_errors"] = (
            institutional_intelligence_errors
        )

        scoring_completed_at = datetime.utcnow()
        timings["total_scoring_seconds"] = round((scoring_completed_at - scoring_started_at).total_seconds(), 2)

        aggregate = {}
        for row in timings["per_symbol"]:
            for k, v in row.items():
                if k.endswith("_seconds") and k != "total_symbol_seconds":
                    aggregate[k] = round(aggregate.get(k, 0) + (v or 0), 2)

        timings["aggregate_engine_seconds"] = aggregate
        timings["slowest_symbols"] = sorted(
            timings["per_symbol"],
            key=lambda x: x.get("total_symbol_seconds") or 0,
            reverse=True
        )[:10]

        return {
            "timestamp": scoring_completed_at.isoformat(),
            "scoring_started_at": scoring_started_at.isoformat(),
            "scoring_completed_at": scoring_completed_at.isoformat(),
            "symbols_scored": len(opportunities),
            "opportunity_scoring_timings": timings,
            "opportunities": opportunities,
            "institutional_intelligence_mode": "ADAPTIVE_BUDGET_OBSERVATION_ONLY",
            "unusual_whales_budget_policy": uw_budget_policy,
            "institutional_intelligence_symbols": institutional_intelligence_symbols,
            "institutional_intelligence_errors": institutional_intelligence_errors,
            "execution_enabled": False,
            "status": "OPPORTUNITY_SCORING_COMPLETE"
        }
