from datetime import datetime

from app.routes.greyline_market_battlefield_summary import greyline_market_battlefield_summary
from app.services.options_cycle_engine import OptionsCycleEngine
from app.services.options_dynamic_position_sizing_engine import OptionsDynamicPositionSizingEngine


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
            max_position_pct = OptionsDynamicPositionSizingEngine().max_position_pct(score)
            r = OptionsCycleEngine().run(
                symbol=symbol,
                option_type=option_type,
                max_position_pct=max_position_pct,
                candidate_score=score,
            )
            ledger_result = r.get("paper_trade") or {}

            results.append({
                "symbol": symbol,
                "option_type": option_type,
                "candidate_result": result,
                "candidate_score": c.get("score") or c.get("composite_score"),
                "paper_trade_recorded": r.get("paper_trade_recorded"),
                "duplicate_blocked": r.get("duplicate_blocked"),
                "selected_option_symbol": (((r.get("top_candidate") or {}).get("Legs") or [{}])[0]).get("Symbol"),
                "block_reason": ledger_result.get("reason"),
                "position_sizing": ledger_result.get("position_sizing"),
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
