from datetime import datetime, timezone

from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine
from app.services.execution_authority_engine import ExecutionAuthorityEngine


class OptionsCycleEngine:

    # OptionsEntryQualityGateEngine rejects any entry under 7 DTE, so the contract we
    # pick must clear that floor or the trade is dead on arrival.
    MIN_ENTRY_DTE = 7

    def _select_expiration(self, symbol, min_dte=None, today=None):
        """Nearest listed expiration that satisfies the minimum-DTE entry rule.

        The expiration used to be hardcoded ("2026-07-17"), and the sweep never passed
        one. Once the calendar drifted inside the 7-DTE floor, that frozen date meant
        the quality gate rejected EVERY options entry no matter how strong the signal.
        An expiry has to be chosen relative to today, not pinned to a literal.
        """
        min_dte = self.MIN_ENTRY_DTE if min_dte is None else min_dte
        today = today or datetime.now(timezone.utc).date()

        listing = TradeStationOptionChainLiveEngine().get_expirations(symbol)
        candidates = []
        for raw in listing.get("expirations") or []:
            try:
                d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue
            candidates.append(((d - today).days, d))

        eligible = sorted(d for dte, d in candidates if dte >= min_dte)
        if eligible:
            return eligible[0].isoformat()

        # No expiry clears the floor (thin/short chain). Return the furthest one we
        # know of and let the quality gate make the call — better than a stale literal.
        furthest = sorted(d for _, d in candidates)
        return furthest[-1].isoformat() if furthest else None

    def run(
        self,
        symbol="NVDA",
        option_type="CALL",
        expiration=None,
        max_position_pct=0.05,
        candidate_score=None,
        regime_calibration=None,
        enforce_authority=False,
        account_equity=10000.0,
        max_contracts=None,
    ):
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

        if not expiration:
            expiration = self._select_expiration(symbol)
            if not expiration:
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "system": "GreyLine",
                    "symbol": symbol,
                    "option_type": option_type,
                    "paper_trade_recorded": False,
                    "reason": "NO_ELIGIBLE_EXPIRATION",
                    "status": "OPTIONS_CYCLE_NO_EXPIRATION",
                }

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

        # Sizing base defaults to the full $10k for standalone callers, but the momentum
        # options engine passes the account's FREE cash here so a new option is only ever
        # sized against dollars the equity book hasn't already spent.
        account_equity = float(account_equity or 10000.0)
        max_position_dollars = account_equity * float(max_position_pct or 0.05)

        from app.services.options_execution_cost_engine import OptionsExecutionCostEngine
        _coster = OptionsExecutionCostEngine()

        affordable_candidates = [
            c for c in candidates
            if float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0) > 0
            and float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0) * 100 <= max_position_dollars
            # reject contracts too expensive to TRADE (spread+fee round-trip), not just too
            # expensive to buy — the same cost gate the momentum executing path uses, so the
            # plan and the cycle never diverge on which contract is acceptable.
            and _coster.viable(c.get("Bid"), c.get("Ask"), c.get("Mid"))[0]
        ]

        ranked = sorted(
            affordable_candidates,
            key=lambda c: (
                -_coster.rank_bucket(c.get("Bid"), c.get("Ask"), c.get("Mid")),  # cheapest-to-trade first
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
                    regime_calibration=regime_calibration,
                    sizing_base=account_equity,
                    max_contracts=max_contracts,
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
            "regime_calibration": regime_calibration,
            "regime_position_multiplier": (
                (regime_calibration or {}).get(
                    "position_multiplier"
                )
            ),
            "regime_execution_allowed": (
                (regime_calibration or {}).get(
                    "execution_allowed"
                )
            ),
            "top_candidate": top,
            "paper_trade_recorded": paper_trade_recorded,
            "duplicate_blocked": duplicate_blocked,
            "paper_trade": paper_trade,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "OPTIONS_CYCLE_READY" if top else "OPTIONS_CYCLE_NO_CANDIDATE",
        }
