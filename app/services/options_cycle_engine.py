from datetime import datetime

from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine


class OptionsCycleEngine:

    def run(self, symbol="NVDA", option_type="CALL", expiration="2026-07-17"):
        symbol = (symbol or "NVDA").upper().strip()
        option_type = (option_type or "CALL").upper().strip()

        chain = TradeStationOptionChainLiveEngine().get_chain_snapshot(
            symbol=symbol,
            expiration=expiration,
            option_type="All",
            max_contracts=50,
        )

        contracts = chain.get("contracts", [])

        side = "Put" if option_type == "PUT" else "Call"

        candidates = [
            c for c in contracts
            if c.get("Side") == side
            and c.get("Legs")
            and float(c.get("Mid") or 0) > 0
        ]

        ranked = sorted(
            candidates,
            key=lambda c: (
                int(c.get("DailyOpenInterest") or 0),
                -abs(float(c.get("Delta") or 0) - 0.40),
                -float(c.get("Mid") or 0),
            ),
            reverse=True,
        )

        top = ranked[0] if ranked else None

        paper_trade = None
        paper_trade_recorded = False

        duplicate_blocked = False

        if top:
            leg = (top.get("Legs") or [{}])[0]
            option_symbol = leg.get("Symbol")

            ledger = OptionsPaperTradeLedgerEngine()

            if ledger.open_position_exists(option_symbol):
                duplicate_blocked = True
            else:
                paper_trade = ledger.record_trade(top)
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
            "top_candidate": top,
            "paper_trade_recorded": paper_trade_recorded,
            "duplicate_blocked": duplicate_blocked,
            "paper_trade": paper_trade,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_CYCLE_READY" if top else "OPTIONS_CYCLE_NO_CANDIDATE",
        }
