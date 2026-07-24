"""Trade the strategy's directional picks as OPTIONS, not shares — the options-trader core.

Operator directive: GreyLine trades options, not stocks. This bridges the directional
signal to options execution: each pick becomes a call (bullish) or put (bearish), gated by
whether a $10k account can actually hold the contract, with the validated Dynamic-TPS 4-TP
exit doctrine attached.

Two realities are built IN rather than argued about, so this is a DISCIPLINED options
trader, not a naive one:

  * AFFORDABILITY GATE. Most high-priced names are untradeable as options at $10k — a
    near-money SNDK call is ~$17,000/contract against a $1,000 slice. Those are SKIPPED and
    reported, never force-sized. Only names whose cheapest usable contract fits the per-name
    budget are traded. As the account grows, more names clear the gate automatically.

  * THETA-AWARE EXPIRY. The directional edge plays out over days, so a weekly option bleeds
    to decay before the move arrives. This prefers ~30-45 DTE, far enough out that theta is
    slow over the intended hold, and never the front-week contract.

The honest caveat, once: on a thin momentum edge (~0.23%/5d) options still lose to premium
and theta — this engine does not manufacture edge, it executes whatever signal drives it as
options. Its value is being READY for a signal with the conviction to justify options
(the flow doctrine, if it proves out), while doing exactly what the operator directed now.
"""

from datetime import datetime, timedelta, timezone

from app.services.options_cycle_engine import OptionsCycleEngine
from app.services.options_dynamic_tps_engine import OptionsDynamicTPSEngine
from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
from app.services.trade_doctrine_engine import TradeDoctrineEngine


class MomentumOptionsExecutionEngine:

    TARGET_DTE = 35            # ~5 weeks: past the front-week theta cliff, still liquid
    MIN_DTE = 21
    MAX_DTE = 60
    TARGET_DELTA = 0.40        # directional target for contract scoring (matches OptionsCycleEngine)

    # CONCENTRATED by default: a $10k options book cannot spread across 10 names and hold
    # anything (only the cheapest option clears the budget). Fewer names x more dollars is
    # the only shape that trades real contracts at a small account, and it aligns with the
    # no-reserve directive — 100% of capital across a handful of highest-conviction picks.
    CANDIDATE_POOL = 25       # scan this many top-conviction picks for affordable options
    CONTRACTS_PER_NAME = 1    # one contract of each name's best affordable option, so the
                              # cash spreads across the top names instead of loading one

    def __init__(self, capital_base=10000.0, max_position_pct=1.0, top_n=5):
        # max_position_pct=1.0: the affordability ceiling is CASH ON HAND, not a fixed
        # fraction of it. The per-name contract cap (CONTRACTS_PER_NAME) keeps the book
        # spread across several names rather than concentrating cash into one.
        self.capital_base = float(capital_base)
        self.max_position_pct = float(max_position_pct)
        self.top_n = int(top_n)
        self.cycle = OptionsCycleEngine()
        self.chain = TradeStationOptionChainLiveEngine()
        self.tps = OptionsDynamicTPSEngine()
        self.doctrine = TradeDoctrineEngine()

    # ---- expiry selection (theta-aware) ------------------------------------
    def _target_expiration(self, symbol, today=None):
        """Nearest listed expiry to TARGET_DTE within [MIN_DTE, MAX_DTE], or None.

        Unlike the entry-quality floor (>= 7 DTE), a directional hold wants distance from the
        theta cliff, so this centres on ~35 DTE rather than grabbing the nearest weekly.
        """
        today = today or datetime.now(timezone.utc).date()
        listing = self.chain.get_expirations(symbol) or {}
        best, best_gap = None, None
        for raw in listing.get("expirations") or []:
            try:
                d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue
            dte = (d - today).days
            if self.MIN_DTE <= dte <= self.MAX_DTE:
                gap = abs(dte - self.TARGET_DTE)
                if best is None or gap < best_gap:
                    best, best_gap = d.isoformat(), gap
        return best

    # ---- per-name contract selection ---------------------------------------
    def _affordable_contract(self, symbol, option_type, budget, expiration):
        """The BEST usable contract that fits `budget` — scored by GreyLine's contract
        ranking, NOT by cheapness. `budget` is cash on hand: affordability is a hard ceiling,
        not the selection driver. Among everything we can actually pay for, pick the highest-
        quality contract (most open interest, then delta nearest the directional target) —
        the same ranking OptionsCycleEngine uses, so the plan and the executing cycle agree.

        Returns (contract, cost, n_contracts) or None.
        """
        snap = self.chain.get_chain_snapshot(symbol=symbol, expiration=expiration,
                                             option_type="Call" if option_type == "CALL" else "Put",
                                             max_contracts=50)
        side = "Call" if option_type == "CALL" else "Put"
        from app.services.options_execution_cost_engine import OptionsExecutionCostEngine
        coster = OptionsExecutionCostEngine()

        affordable, cost_rejected = [], 0
        for c in snap.get("contracts", []) or []:
            if c.get("Side") and c.get("Side") != side:
                continue
            try:
                px = float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0)
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            cost = px * 100
            if cost > budget:
                continue
            # Reject contracts too EXPENSIVE TO TRADE — the spread+fee round-trip that selection
            # used to ignore. This is what would have refused the 28%-wide contract we held.
            ok, est = coster.viable(c.get("Bid"), c.get("Ask"), c.get("Mid"))
            if not ok:
                cost_rejected += 1
                continue
            affordable.append((c, cost, est))
        if not affordable:
            return None
        # Cost is now the PRIMARY driver: cheapest-to-trade bucket first (which pulls toward tight,
        # liquid, higher-delta strikes on its own), then liquidity, then delta near the target.
        affordable.sort(key=lambda cc: (
            -coster.rank_bucket(cc[0].get("Bid"), cc[0].get("Ask"), cc[0].get("Mid")),
            int(cc[0].get("DailyOpenInterest") or 0),
            -abs(float(cc[0].get("Delta") or 0) - self.TARGET_DELTA),
        ), reverse=True)
        contract, cost, _est = affordable[0]
        return contract, cost, max(1, int(budget // cost))

    # ---- contract board (top-scoring + affordable) -------------------------
    def _best_scored_contract(self, symbol, option_type, expiration):
        """The single best contract for a name by GreyLine's contract score (open interest,
        then delta nearest the target) — REGARDLESS of cost. Returns a dict or None."""
        snap = self.chain.get_chain_snapshot(symbol=symbol, expiration=expiration,
                                             option_type="Call" if option_type == "CALL" else "Put",
                                             max_contracts=50)
        side = "Call" if option_type == "CALL" else "Put"
        cands = []
        for c in snap.get("contracts", []) or []:
            if c.get("Side") and c.get("Side") != side:
                continue
            try:
                px = float(c.get("Ask") or c.get("Mid") or c.get("Last") or 0)
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            cands.append((c, px * 100, int(c.get("DailyOpenInterest") or 0), float(c.get("Delta") or 0)))
        if not cands:
            return None
        cands.sort(key=lambda x: (x[2], -abs(x[3] - self.TARGET_DELTA)), reverse=True)
        c, cost, oi, delta = cands[0]
        leg = (c.get("Legs") or [{}])[0]
        return {
            "symbol": symbol, "option_type": option_type,
            "option_symbol": leg.get("Symbol") or c.get("Symbol"),
            "strike": c.get("Strike") or leg.get("StrikePrice"),
            "premium_per_contract": round(cost / 100, 2), "cost": round(cost, 2),
            "open_interest": oi, "delta": round(delta, 3),
        }

    def contract_board(self, targets, cash_on_hand, pool=10, top_affordable=5):
        """Score the best contract for each top candidate (GreyLine's OI/delta score), then
        split into: the single TOP-scoring contract (affordable or NOT — the ideal we'd take
        with unlimited cash), and the top-N AFFORDABLE contracts by score (what we can buy on
        cash on hand). Row 1 of the board is the top-scoring; the rest are the affordable set.
        """
        scored = []
        for t in targets[:pool]:
            symbol = t.get("symbol")
            option_type = "PUT" if str(t.get("side", "")).upper() in ("SELL", "SELL_SHORT", "SHORT") else "CALL"
            exp = self._target_expiration(symbol)
            if not exp:
                continue
            best = self._best_scored_contract(symbol, option_type, exp)
            if not best:
                continue
            best["expiration"] = exp
            try:
                best["dte"] = (datetime.fromisoformat(str(exp)[:10]).date()
                               - datetime.now(timezone.utc).date()).days
            except (ValueError, TypeError):
                best["dte"] = None
            conv = t.get("conviction")
            best["conviction"] = conv
            # 0-100 signal score (same scale the entry-quality gate uses): conviction/2*100.
            best["score"] = round(min(2.0, float(conv or 0)) / 2.0 * 100, 1)
            best["directional_bias"] = t.get("directional_bias")
            best["affordable"] = best["cost"] <= float(cash_on_hand or 0)
            scored.append(best)
        # GreyLine contract score: open interest first, then delta nearest the target.
        scored.sort(key=lambda s: (s["open_interest"], -abs(s["delta"] - self.TARGET_DELTA)), reverse=True)
        top_scoring = scored[0] if scored else None
        affordable = [s for s in scored if s["affordable"]][:top_affordable]
        return {
            "cash_on_hand": round(float(cash_on_hand or 0), 2),
            "top_scoring_contract": top_scoring,
            "affordable_contracts": affordable,
            "scanned": len(scored),
        }

    # ---- free cash across BOTH books ---------------------------------------
    def _free_cash(self):
        """Idle cash the options book may draw on — capital_base minus what BOTH books hold.

        Operator directive: keep the open equity positions AND run options, balanced by the
        paper cash balance. The equity shares already hold part of the $10k; sizing options
        against the full base would deploy the same dollars twice. This routes through the
        options ledger's cross-book cash calc (open equity cost + open options cost + realized
        P&L) so every layer agrees on one number.
        """
        from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine
        try:
            return OptionsPaperTradeLedgerEngine().account_free_cash(self.capital_base)
        except Exception:
            return self.capital_base

    # ---- plan (dry-run capable) --------------------------------------------
    def plan(self, targets, sizing_base=None):
        """Turn directional picks into an options plan — no orders placed.

        `targets`: list of {symbol, side, directional_bias, last_close, conviction, ...}
        from MomentumReversalStrategyEngine.select. `sizing_base` is the cash to size against
        (free cash when the equity book is co-resident); it defaults to live free cash so a
        standalone plan() call is honest too. Returns the tradeable options plus the skipped
        names with reasons, so the affordability truth is visible, never hidden.
        """
        base = self._free_cash() if sizing_base is None else float(sizing_base)
        # Affordability ceiling = CASH ON HAND, not a fixed fraction of it. We buy the best
        # contract the account can actually pay for; the per-name %-cap no longer throttles
        # which contracts the scorer is allowed to consider.
        budget = base
        tradeable, skipped = [], []
        # Scan the FULL ranked list and take affordable picks in conviction order, up to
        # top_n positions — NOT the top_n by rank. The signal's highest-conviction names are
        # its highest-priced, whose options price out; the affordable options sit lower in
        # the ranking (RKLB, GLW). Concentrating into the top would trade nothing. This
        # trades the best AFFORDABLE picks — an honest compromise a small account must make
        # until it grows into the pricier names.
        for t in targets[:self.CANDIDATE_POOL]:
            if len(tradeable) >= self.top_n:
                break
            symbol = t.get("symbol")
            option_type = "PUT" if str(t.get("side", "")).upper() in ("SELL", "SELL_SHORT", "SHORT") else "CALL"
            exp = self._target_expiration(symbol)
            if not exp:
                skipped.append({"symbol": symbol, "reason": "NO_EXPIRY_IN_DTE_WINDOW"})
                continue
            got = self._affordable_contract(symbol, option_type, budget, exp)
            if not got:
                skipped.append({"symbol": symbol, "option_type": option_type,
                                "reason": "NO_AFFORDABLE_CONTRACT", "budget": round(budget, 2)})
                continue
            contract, cost, n = got
            # ATR-free: without an ATR feed here the exit ladder is expressed in % of the
            # option's own premium via the Dynamic-TPS engine's contract allocation, which
            # is what actually gets managed. Entry premium is the reference the stop ratchets
            # from. (ATR-based underlying targets are a later refinement.)
            alloc = self.tps.allocate(n)
            option_symbol = (contract.get("Legs") or [{}])[0].get("Symbol") or contract.get("Symbol")
            tradeable.append({
                "symbol": symbol, "option_type": option_type, "expiration": exp,
                "option_symbol": option_symbol,
                "strike": contract.get("Strike"), "premium_per_contract": round(cost / 100, 2),
                "contracts": n, "cost": round(cost * n, 2),
                "directional_bias": t.get("directional_bias"),
                "conviction": t.get("conviction"),
                "exit": {"mode": alloc["mode"], "contracts_at_target": alloc["targets"],
                         "runner": alloc["runner"],
                         "doctrine": "Dynamic-TPS: bank at targets where size allows, "
                                     "ratchet the stop on every target reached, run the tail"},
            })
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "MomentumOptionsExecutionEngine",
            "free_cash": round(base, 2),
            "capital_base": round(self.capital_base, 2),
            "per_name_budget": round(budget, 2),
            "tradeable": tradeable,
            "skipped": skipped,
            "tradeable_count": len(tradeable),
            "skipped_count": len(skipped),
            "note": (f"{len(tradeable)} of {min(len(targets), self.top_n)} picks are tradeable "
                     f"as options against ${base:,.0f} free cash (of ${self.capital_base:,.0f} "
                     "base; the rest held by the open equity book). The affordable set grows "
                     "as equity closes out or the account grows."),
            "status": "MOMENTUM_OPTIONS_PLAN_READY",
        }

    def run_cycle(self):
        """Full scheduler cycle: gate on market-open, get the signal's picks, execute.

        Self-contained so the scheduler wiring is one call. Kill-switch and per-name
        affordability are enforced inside execute(); this adds the market-open gate (never
        open a new options position into a closed tape) and the data-staleness guard the
        equity path uses, then hands the ranked picks to execution.
        """
        from app.services.market_hours_engine import MarketHoursEngine
        from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine

        if MarketHoursEngine().status().get("is_regular_session") is not True:
            return {"engine": "MomentumOptionsExecutionEngine", "placed_count": 0,
                    "status": "OPTIONS_REBALANCE_SKIPPED_MARKET_CLOSED"}
        # LIQUID-WINDOW GATE: option spreads are widest right after the open and before the close.
        # A multi-day thesis does not need to pay that tax — wait for the liquid mid-session. This
        # gates ENTRIES only; exits are never blocked here (urgency handles that on the exit side).
        from app.services.session_liquidity_window_engine import SessionLiquidityWindowEngine
        _liq = SessionLiquidityWindowEngine().status()
        if not _liq["in_liquid_window"]:
            return {"engine": "MomentumOptionsExecutionEngine", "placed_count": 0,
                    "liquidity_window": _liq,
                    "status": "OPTIONS_ENTRY_SKIPPED_OUTSIDE_LIQUID_WINDOW"}
        strat = MomentumReversalStrategyEngine()
        series, asof, source = strat.universe()
        # Same data-quality bar as the equity rebalance — never enter on stale prices.
        if source not in ("TRADESTATION_LIVE", "TRADESTATION_LIVE_CACHED"):
            return {"engine": "MomentumOptionsExecutionEngine", "placed_count": 0,
                    "as_of": asof, "data_source": source,
                    "status": "OPTIONS_REBALANCE_SKIPPED_STALE_DATA"}
        targets, _ = strat.select(series)

        # MARKET-REGIME GATE: the signal buys dips, which is a catastrophe in a downtrend
        # where dips keep dipping. Drop BULLISH dip-buys when the broad index is below its
        # 200DMA (RISK_OFF); bearish/put setups still pass. Tail-risk protection, not alpha:
        # validated flat on average return but far thinner left tail above the 200DMA.
        from app.services.market_regime_gate_engine import MarketRegimeGateEngine
        targets, regime_dropped, regime = MarketRegimeGateEngine().filter_targets(targets)

        out = self.execute(targets)
        out["as_of"] = asof
        out["regime"] = regime
        out["regime_blocked"] = regime_dropped
        if regime_dropped:
            out["regime_blocked_count"] = len(regime_dropped)
        return out

    def execute(self, targets):
        """Place the tradeable options picks via OptionsCycleEngine (paper).

        THIS engine is the signal authority — the momentum pick IS the decision — so it
        checks the paper-execution kill-switch itself (exactly as the equity rebalance
        does) and then places with enforce_authority=False. OptionsCycleEngine's own
        authority gate ties to a DIFFERENT signal (the master decision engine), which does
        not apply to a momentum-driven options book; but its kill-switch guard does, so we
        enforce that guard here rather than lose it. The options ledger's own gates
        (market hours, entry quality, exposure, cash, reliability) still apply at placement.
        """
        from os import getenv
        if (getenv("GREYLINE_PAPER_EXECUTION_ENABLED", "") or "").lower() != "true":
            return {"timestamp": datetime.utcnow().isoformat(),
                    "engine": "MomentumOptionsExecutionEngine", "placed": [], "blocked": [],
                    "priced_out": [], "placed_count": 0,
                    "status": "MOMENTUM_OPTIONS_EXECUTION_KILL_SWITCH_DISABLED"}

        # One free-cash reading drives both the plan and every placement, so the whole batch
        # sizes against the same balance (equity book already subtracted). The ledger still
        # re-checks live cash on each record, so a name that would breach is blocked, not
        # forced — this just prevents the batch from ever assuming the full $10k.
        from app.services.options_entry_forecast_engine import OptionsEntryForecastEngine
        from app.services.options_entry_learning_engine import OptionsEntryLearningEngine
        forecaster = OptionsEntryForecastEngine()

        free_cash = self._free_cash()
        plan = self.plan(targets, sizing_base=free_cash)
        placed, blocked, to_book = [], [], []
        for t in plan["tradeable"]:
            # The options entry-quality gate scores on the retired signal's 0-100 scale and
            # requires >= 85. The momentum path scores conviction on 0-2 (momentum percentile
            # + reversal percentile). Translate it — conviction/2*100 — so a high-conviction
            # momentum pick (e.g. 1.97 -> ~98) clears the gate instead of defaulting to 0.
            candidate_score = round(min(2.0, float(t.get("conviction") or 0)) / 2.0 * 100, 1)
            result = self.cycle.run(
                symbol=t["symbol"],
                option_type=t["option_type"],
                expiration=t["expiration"],
                max_position_pct=self.max_position_pct,
                candidate_score=candidate_score,
                enforce_authority=False,
                account_equity=free_cash,
                max_contracts=self.CONTRACTS_PER_NAME,
            )
            recorded = bool(result.get("paper_trade_recorded"))
            rec = {"symbol": t["symbol"], "option_type": t["option_type"],
                   "status": result.get("status"), "recorded": recorded,
                   "reason": result.get("reason")}
            (placed if recorded else blocked).append(rec)
            # Book EXACTLY the contract the ledger recorded — OptionsCycleEngine picks the
            # contract (by OI/delta), which can differ in strike AND size from the plan's
            # cheapest-affordable probe. Booking the plan's contract instead let the broker
            # and the ledger drift apart (the Reality Guard caught it). Mirror the recorded
            # trade so ledger == broker, always one selection.
            if recorded:
                rt = (result.get("paper_trade") or {}).get("trade") or {}
                osym, ncon = rt.get("option_symbol"), int(rt.get("contracts") or 0)
                if osym and ncon > 0:
                    # Phase 2: forecast the best LIMIT buy price from the contract's quote
                    # instead of paying the market. The learning engine's aggressiveness sets
                    # how hard we chase; the outcome is logged so it can refine.
                    fc = forecaster.forecast(rt.get("bid"), rt.get("ask"), rt.get("entry_mid"))
                    to_book.append({"option_symbol": osym, "contracts": ncon,
                                    "limit_price": fc["limit_price"], "_forecast": fc})

        # Mirror the recorded options into the TradeStation SIM account as REAL BUYTOOPEN
        # LIMIT orders at the forecasted price — the Phase-2 entry. Best-effort: a broker
        # hiccup must never break the decision path, and the Reality Guard flags divergence.
        sim_booking = {"status": "SIM_BOOKING_DISABLED", "placed": 0}
        try:
            from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
            sim_booking = GreyLineSimExecutionEngine().book_option_opens(to_book)
            # Log each forecast as PENDING with its order id so fills can be reconciled and
            # the aggressiveness refined.
            learning = OptionsEntryLearningEngine()
            booked_by_sym = {b.get("option_symbol"): b for b in (sim_booking.get("booked") or [])}
            for item in to_book:
                b = booked_by_sym.get(item["option_symbol"], {})
                learning.record_forecast(item["option_symbol"], item.get("_forecast") or {},
                                         item["contracts"], b.get("order_id"), ok=b.get("ok"))
        except Exception as e:
            sim_booking = {"status": "SIM_OPTIONS_BOOKING_ERROR", "error": str(e)[:200], "placed": 0}

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "MomentumOptionsExecutionEngine",
            "free_cash": free_cash, "per_name_budget": plan.get("per_name_budget"),
            "placed": placed, "blocked": blocked,
            "priced_out": plan["skipped"],
            "placed_count": len(placed),
            "sim_booking": sim_booking,
            "status": "MOMENTUM_OPTIONS_EXECUTION_COMPLETE",
        }
