from datetime import datetime

from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine
from app.services.execution_authority_engine import ExecutionAuthorityEngine


class OptionsCycleEngine:

    def run(self, symbol="NVDA", option_type="CALL", expiration="2026-07-17", max_position_pct=0.05, candidate_score=None, enforce_authority=False):
        if enforce_authority:
            authority = ExecutionAuthorityEngine().evaluate()
            if not authority.get("paper_execution_allowed"):
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "system": "GreyLine",
                    "source": "OPTIONS_CYCLE_ENGINE",
                    "paper_trade_recorded": False,
                    "reason": authority.get("reason"),
                    "execution_authority": authority.get("execution_authority"),
                    "status": "OPTIONS_CYCLE_AUTHORITY_BLOCKED",
                }

        symbol = (symbol or "NVDA").upper().strip()
        option_type = (option_type or "CALL").upper().strip()

        chain = TradeStationOptionChainLiveEngine().get_chain_snapshot(
            symbol=symbol,
            expiration=expiration,
            option_type="All",
            max_contracts=10,
        )

        contracts = chain.get("contracts", [])

        side = "Put" if option_type == "PUT" else "Call"

        candidates = [
            c for c in contracts
            if c.get("Side") == side
            and c.get("Legs")
            and float(c.get("Mid") or 0) > 0
        ]

        account_equity = 10000.0
        max_position_dollars = account_equity * float(max_position_pct or 0.05)

        affordable_candidates = [
            c for c in candidates
            if float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0) > 0
            and float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0) * 100 <= max_position_dollars
        ]

        ranked = sorted(
            affordable_candidates,
            key=lambda c: (
                int(c.get("DailyOpenInterest") or 0),
                -abs(float(c.get("Delta") or 0) - 0.40),
                -float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0),
            ),
            reverse=True,
        )

        top = ranked[0] if ranked else None

        paper_trade = None
        paper_trade_recorded = False

        duplicate_blocked = False

        if top:
            top["underlying"] = symbol
            top["Underlying"] = symbol
            leg = (top.get("Legs") or [{}])[0]
            leg["Underlying"] = symbol
            option_symbol = leg.get("Symbol")

            ledger = OptionsPaperTradeLedgerEngine()

            history = ledger.history()
            existing = history.get("open_positions") or history.get("open_trades") or history.get("trades") or []
            same_underlying_open = [
                t for t in existing
                if str(t.get("underlying") or "").upper() == symbol
                and str(t.get("option_type") or "").upper() == side.upper()
                and str(t.get("status") or "").upper() == "OPEN"
            ]

            if ledger.open_position_exists(option_symbol) or same_underlying_open:
                duplicate_blocked = True
                paper_trade = {
                    "paper_trade_recorded": False,
                    "reason": "DUPLICATE_OPEN_UNDERLYING_OPTION_POSITION",
                    "option_symbol": option_symbol,
                    "underlying": symbol,
                    "option_type": side,
                    "open_same_underlying_count": len(same_underlying_open),
                    "status": "OPTIONS_PAPER_TRADE_DUPLICATE_BLOCKED",
                }
            else:
                paper_trade = ledger.record_trade(
                    top,
                    max_position_pct=max_position_pct,
                    candidate_score=candidate_score,
                )
                paper_trade_recorded = paper_trade.get("paper_trade_recorded") is True

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "OPTIONS_CYCLE_ENGINE",
            "symbol": symbol,
            "expiration": expiration,
            "contracts_scanned": len(contracts),
            "option_type": option_type,
            "side": side,
            "contracts_matching_side_found": len(candidates),
            "affordable_contracts_found": len(affordable_candidates),
            "max_position_pct": max_position_pct,
            "max_position_dollars": round(max_position_dollars, 2),
            "top_candidate": top,
            "paper_trade_recorded": paper_trade_recorded,
            "duplicate_blocked": duplicate_blocked,
            "paper_trade": paper_trade,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_CYCLE_READY" if top else "OPTIONS_CYCLE_NO_CANDIDATE",
        }
