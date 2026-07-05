from datetime import datetime

from app.routes.greyline_market_battlefield_summary import greyline_market_battlefield_summary
from app.services.options_cycle_engine import OptionsCycleEngine
from app.services.options_dynamic_position_sizing_engine import OptionsDynamicPositionSizingEngine
from app.services.signal_reliability_engine import SignalReliabilityEngine
from app.services.institutional_trade_lifecycle_engine import InstitutionalTradeLifecycleEngine
from app.services.operator_event_bus_engine import OperatorEventBusEngine


class OptionsPaperExecutionSweepEngine:
    def run(self, limit=10):
        battlefield = greyline_market_battlefield_summary(force_refresh=True)
        candidates = battlefield.get("top_candidates") or []

        results = []

        for c in candidates[:limit]:
            symbol = c.get("symbol")
            option_type = c.get("option_type")
            result = c.get("result")

            if result != "EXECUTE":
                results.append({
                    "symbol": symbol,
                    "option_type": option_type,
                    "candidate_result": result,
                    "paper_trade_recorded": False,
                    "reason": "NOT_EXECUTE_SIGNAL",
                    "status": "OPTIONS_PAPER_SWEEP_SKIPPED",
                })
                continue

            if not symbol or not option_type:
                results.append({
                    "symbol": symbol,
                    "option_type": option_type,
                    "candidate_result": result,
                    "paper_trade_recorded": False,
                    "reason": "MISSING_SYMBOL_OR_OPTION_TYPE",
                    "status": "OPTIONS_PAPER_SWEEP_BLOCKED",
                })
                continue

            score = c.get("score") or c.get("composite_score")
            reliability = SignalReliabilityEngine().evaluate(c)

            lifecycle = InstitutionalTradeLifecycleEngine().evaluate({
                "institutional_flow_direction": c.get("institutional_flow_direction"),
                "institutional_flow_momentum_score": c.get("institutional_flow_momentum_score"),
                "institutional_flow_decay": c.get("institutional_flow_decay"),
                "institutional_conviction_score": c.get("institutional_conviction_score"),
            })

            max_position_pct = (
                OptionsDynamicPositionSizingEngine().max_position_pct(
                    score,
                    reliability.get("signal_reliability_score"),
                )
                * lifecycle.get("position_multiplier", 1.0)
            )
            r = OptionsCycleEngine().run(
                symbol=symbol,
                option_type=option_type,
                max_position_pct=max_position_pct,
                candidate_score=score,
            )
            ledger_result = r.get("paper_trade") or {}

            if r.get("paper_trade_recorded") is True:
                OperatorEventBusEngine().publish(
                    source="OptionsPaperExecutionSweepEngine",
                    category="POSITION_OPENED",
                    severity="INFO",
                    title="New Option Position Opened",
                    message=f"{symbol} {option_type} paper option position opened.",
                    symbol=symbol,
                    trade_id=ledger_result.get("trade_id") or (((r.get("top_candidate") or {}).get("Legs") or [{}])[0]).get("Symbol"),
                    ack_required=False,
                    payload={
                        "candidate": c,
                        "cycle_result": r,
                        "paper_trade": ledger_result,
                    },
                )

            results.append({
                "symbol": symbol,
                "option_type": option_type,
                "candidate_result": result,
                "candidate_score": c.get("score") or c.get("composite_score"),
                "signal_reliability_score": reliability.get("signal_reliability_score"),
                "signal_reliability_grade": reliability.get("signal_reliability_grade"),
                "signal_reliability": reliability,
                "paper_trade_recorded": r.get("paper_trade_recorded"),
                "duplicate_blocked": r.get("duplicate_blocked"),
                "selected_option_symbol": (((r.get("top_candidate") or {}).get("Legs") or [{}])[0]).get("Symbol"),
                "block_reason": ledger_result.get("reason"),
                "position_sizing": ledger_result.get("position_sizing"),
                "trade_phase": lifecycle.get("trade_phase"),
                "trade_action": lifecycle.get("trade_action"),
                "stop_adjustment": lifecycle.get("stop_adjustment"),
                "position_multiplier": lifecycle.get("position_multiplier"),
                "engine_status": r.get("status"),
                "status": "OPTIONS_PAPER_SWEEP_EVALUATED",
            })

        recorded = [r for r in results if r.get("paper_trade_recorded") is True]
        duplicates = [r for r in results if r.get("duplicate_blocked") is True]
        skipped = [r for r in results if r.get("status") != "OPTIONS_PAPER_SWEEP_EVALUATED"]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_PAPER_EXECUTION_SWEEP",
            "candidates_checked": len(results),
            "paper_trades_recorded": len(recorded),
            "duplicates_blocked": len(duplicates),
            "skipped_count": len(skipped),
            "results": results,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_PAPER_EXECUTION_SWEEP_READY",
        }
