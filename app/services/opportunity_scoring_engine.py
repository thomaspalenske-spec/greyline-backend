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
from app.services.asymmetry_scoring_engine import AsymmetryScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine


class OpportunityScoringEngine:

    def score_opportunities(self, limit=None):
        scoring_started_at = datetime.utcnow()
        timings = {
            "per_symbol": []
        }

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
                "CALL", setup_result, regime_result, trend_persistence_result, equity_flow_result
            )
            bear_conviction = InstitutionalConvictionEngine().score(
                "PUT", setup_result, regime_result, trend_persistence_result, equity_flow_result
            )
            institutional_conviction_score = bull_conviction.get("institutional_conviction_score", 50)
            bear_institutional_conviction_score = bear_conviction.get("institutional_conviction_score", 50)
            t1 = datetime.utcnow()
            symbol_timings["institutional_conviction_seconds"] = round((t1 - t0).total_seconds(), 2)

            bullish_score = round(
                (
                    market_data_score * 0.08
                    + liquidity_score * 0.11
                    + bullish_setup_score * 0.13
                    + regime_score * 0.11
                    + volatility_score * 0.07
                    + expected_value_score * 0.10
                    + trend_persistence_score * 0.09
                    + breadth_score * 0.08
                    + institutional_inflow_score * 0.06
                    + institutional_conviction_score * 0.02
                    + asymmetry_score * 0.08
                    + risk_state_score * 0.07
                ),
                2
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
                    + bear_sponsorship_score * 0.06
                    + bear_institutional_conviction_score * 0.02
                    + bear_asymmetry_score * 0.06
                    + bear_risk_score * 0.05
                ),
                2
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

            if composite_score >= 85 and direction_confidence >= 5:
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

            if (
                regime_result.get("regime") == "WEAK_LIVE"
                or risk_state_result.get("risk_state") in ["DEFENSIVE", "STRESSED"]
            ):
                if result == "EXECUTE":
                    result = "WATCH"

            if (
                regime_result.get("regime") == "WEAK_LIVE"
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

            opportunities.append({
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
                "institutional_conviction_state": bull_conviction.get("institutional_conviction_state") if option_type == "CALL" else bear_conviction.get("institutional_conviction_state"),
                "institutional_conviction_reasons": bull_conviction.get("institutional_conviction_reasons") if option_type == "CALL" else bear_conviction.get("institutional_conviction_reasons"),
                "institutional_conviction_components": bull_conviction.get("institutional_conviction_components") if option_type == "CALL" else bear_conviction.get("institutional_conviction_components"),
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
                "result": result,
                "order_placement_allowed": governor.get("order_placement_allowed"),
                "governor_status": governor.get("status"),
                "execution_enabled": False
            })

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
            "execution_enabled": False,
            "status": "OPPORTUNITY_SCORING_COMPLETE"
        }
