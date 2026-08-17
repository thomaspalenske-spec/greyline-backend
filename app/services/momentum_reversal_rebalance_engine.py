import json
from datetime import datetime
from os import getenv
from pathlib import Path

from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.position_exposure_limit_engine import PositionExposureLimitEngine
from app.services.market_hours_engine import MarketHoursEngine


class MomentumReversalRebalanceEngine:
    """
    Runs the validated strategy forward: each rebalance realizes the prior holdings and
    opens the current top-N, matching the non-overlapping 5-day hold the backtest measured.

    Self-gating so it can live in the always-on scheduler cycle:
      * market must be open (no entries into a closed tape),
      * at least ~5 trading days since the last rebalance (weekly cadence),
      * paper execution enabled, and risk limits respected (opens stop before a breach).

    Sizing is ~75% gross across top-N ($750/name on the $10k book). It was 50%, chosen to
    keep a same-sector cluster clear of the concentration limit — but at $500/name the five
    names priced above $500 (SPY, QQQ, META, SMH, AMD) could not buy a single whole share
    and were dropped as SKIPPED_SUB_SHARE_NOTIONAL. That exclusion is price-correlated, so
    the forward record was measuring a systematically cheaper basket than the strategy the
    backtest validated. At $750/name every universe name is holdable.

    The concentration limit moves with it: at 50% gross a same-sector cluster only breached
    at 10 of 10 names, at 75% it would breach at 7, and TECHNOLOGY is the largest bucket in
    the universe by far — the rebalance stops opening before a breach, so the cap would have
    silently truncated the book and replaced one selection bias with another. Hence
    GREYLINE_MAX_SECTOR_EXPOSURE_PCT=70, which preserves the same 9-of-10 headroom.

    The forward pipeline (fixed-horizon grader, data-integrity) measures the real,
    survivorship-free result from the first fill.
    """

    STATE = Path("app/data/momentum_reversal/rebalance_state.json")
    MIN_CALENDAR_DAYS = 7          # ~5 trading days
    GROSS_TARGET = 1.0            # deploy 100% of capital — no cash reserve (operator directive)
    TRADE_INTENT = "MOMENTUM_REVERSAL"
    LIVE_SOURCES = ("TRADESTATION_LIVE", "TRADESTATION_LIVE_CACHED")
    MAX_STALE_DAYS = 4            # allows a 3-day holiday weekend; beyond it, refuse to trade

    def __init__(self, top_n=None):
        self.strategy = MomentumReversalStrategyEngine(top_n=top_n)
        self.ledger = PaperTradeLedgerEngine()

    def _state(self):
        try:
            return json.loads(self.STATE.read_text())
        except Exception:
            return {}

    def _save_state(self, data):
        self.STATE.parent.mkdir(parents=True, exist_ok=True)
        self.STATE.write_text(json.dumps(data))

    def _due(self, now):
        last = self._state().get("last_rebalance_at")
        if not last:
            return True
        try:
            return (now - datetime.fromisoformat(last)).days >= self.MIN_CALENDAR_DAYS
        except Exception:
            return True

    def _result(self, status, **extra):
        return {"timestamp": datetime.utcnow().isoformat(),
                "engine": "MomentumReversalRebalanceEngine", "status": status, **extra}

    def _staleness(self, source, asof, now):
        """Why the data is unfit to trade on, or None if it's current.

        universe() falls back to the stale CSV feed silently when the live TradeStation
        fetch fails (e.g. token expired). Trading on that would open/close positions at
        two-week-old prices and corrupt both the book and the forward edge measurement —
        the exact silent stale-data failure that has bitten this system repeatedly.
        """
        if source not in self.LIVE_SOURCES:
            return f"live feed unavailable (data source is {source})"
        try:
            bar_date = datetime.fromisoformat(str(asof)[:10]).date()
        except (ValueError, TypeError):
            return f"unusable as-of date: {asof!r}"
        age = (now.date() - bar_date).days
        if age > self.MAX_STALE_DAYS:
            return f"latest bar {asof} is {age} calendar days old (max {self.MAX_STALE_DAYS})"
        return None

    VOL_LOOKBACK = 60          # trailing bars — must match MomentumReversalBacktestEngine

    @classmethod
    def _trailing_vol(cls, closes):
        """Annualised realised vol from the most recent bars. Trailing data only."""
        c = [x for x in (closes or []) if isinstance(x, (int, float)) and x > 0]
        if len(c) < 21:
            return None
        w = c[-(cls.VOL_LOOKBACK + 1):]
        rets = [w[i] / w[i - 1] - 1.0 for i in range(1, len(w))]
        if len(rets) < 20:
            return None
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / len(rets)
        return (var ** 0.5) * (252 ** 0.5) * 100.0

    def rebalance(self, force=False):
        now = datetime.utcnow()

        if (getenv("GREYLINE_PAPER_EXECUTION_ENABLED", "") or "").lower() != "true":
            return self._result("REBALANCE_BLOCKED_EXECUTION_DISABLED", rebalanced=False)

        session = MarketHoursEngine().status()
        if not force and session.get("is_regular_session") is not True:
            return self._result("REBALANCE_SKIPPED_MARKET_CLOSED", rebalanced=False,
                                market_state=session.get("state"))
        if not force and not self._due(now):
            return self._result("REBALANCE_SKIPPED_NOT_DUE", rebalanced=False,
                                last_rebalance_at=self._state().get("last_rebalance_at"))

        # One universe fetch drives both selection and exit pricing.
        series, asof, source = self.strategy.universe()

        # Refuse to trade on stale data — even when forced. `force` may override the
        # timing gates (market-open, cadence), but never the data-quality gate: opening
        # or closing at stale prices is always wrong. Hold the current book instead.
        stale = self._staleness(source, asof, now)
        if stale:
            return self._result("REBALANCE_SKIPPED_STALE_DATA", rebalanced=False,
                                as_of=asof, data_source=source, reason=stale)

        # Use the FULL ranked list, NOT select()'s top-N slice. The filters below (long-only,
        # regime, vol, trash) whittle this down and the free_slots cap in the fill loop takes the
        # top survivors — so clean names ranked below the junk backfill into the book. Filtering
        # the pre-truncated top-N instead was the bug that deployed NOTHING on a 748-clean-signal
        # day: the momentum signal ranks pump-and-dumps/split-artifacts highest, so the top-N was
        # all trash while every tradeable name sat just below the cut.
        _top_n_slice, targets = self.strategy.select(series)   # targets := full ranked list

        # LONG-ONLY. The 2026-07-24 cost-aware backtest showed the market-neutral long-short is
        # not significant while the long-only excess-over-market is — because the SHORT side is
        # survivorship-inflated noise (shorting a survivor-only universe, whose failures are
        # absent, loses). The demonstrable edge is long-side selection, so we trade only it.
        targets = [t for t in targets
                   if str(t.get("directional_bias") or "").upper() == "BULLISH"]

        # REGIME GATE — same brake the options path has: don't buy dips into a confirmed
        # downtrend (SPY < 200DMA). Bearish targets are already gone, so in RISK_OFF this
        # correctly leaves nothing new to open. Tail-risk protection, not alpha.
        from app.services.market_regime_gate_engine import MarketRegimeGateEngine
        from os import getenv as _getenv0
        targets, regime_dropped, regime = MarketRegimeGateEngine().filter_targets(targets)

        # POINT-IN-TIME VOLATILITY CEILING. A ~300%-vol name is a different instrument than a
        # 25%-vol one and swamps an equal-weight book's risk. The ONLY honest way to express
        # that is a rule computed from TRAILING data at the moment of the decision — never by
        # screening the universe on full-sample volatility, which deletes names retroactively
        # using information the strategy could not have had and warps the reality the backtest
        # is meant to measure. Identical logic runs in MomentumReversalBacktestEngine, so live
        # and backtest agree. Backtest: gross Sharpe 0.95 -> 1.07 at this ceiling.
        max_vol = float(_getenv0("GREYLINE_MAX_TRAILING_VOL_PCT", "100") or 100)
        vol_dropped = []
        if max_vol > 0:
            kept = []
            for t in targets:
                v = self._trailing_vol(series.get(t.get("symbol")) or [])
                if v is not None and v > max_vol:
                    vol_dropped.append({"symbol": t.get("symbol"), "trailing_vol_pct": round(v, 1)})
                else:
                    kept.append(t)
            targets = kept

        # FAILSAFE: discard TRASH picks (penny stocks / artifact "momentum" / crashes-not-pullbacks)
        # so GreyLine never EXECUTES on them — it just drops them. Same single filter the dashboard
        # uses to hide them, so display and execution can never disagree on what counts as trash.
        from app.services.trash_pick_filter_engine import TrashPickFilterEngine
        targets, trash_discarded = TrashPickFilterEngine.partition(targets)

        # Exits are owned by MomentumExitManagerEngine (validated H2 doctrine), NOT the
        # rebalance. So the rebalance no longer closes the book — it only TOPS UP: fills
        # empty slots (top_n minus what's still open) with the strongest fresh signals not
        # already held. Positions leave the book when H2 stops or fully scales them out.
        trades = self.ledger._read_all()
        held_trades = [t for t in trades
                       if t.get("status") == "OPEN" and t.get("trade_intent") == self.TRADE_INTENT]
        held = {t.get("symbol") for t in held_trades}

        sleeve_budget = self.strategy.capital_base * self.GROSS_TARGET
        per_name = sleeve_budget / max(1, self.strategy.top_n)      # per-name TARGET/cap (unchanged)
        free_slots = max(0, self.strategy.top_n - len(held))        # legacy count gate (still reported)

        # SIZING MODE. Legacy ("count"): a FIXED number of equal slots, top_n − held. At a small
        # book, whole-share rounding leaves each held name BELOW its per-name target, so real
        # sleeve budget sits IDLE while the count still caps at top_n — a cheap, high-conviction
        # name (e.g. BRUN) can't be secured even though the % allocation isn't spent.
        # BUDGET mode floats the name-count under the %-of-equity budget: it deploys the UNSPENT
        # sleeve dollars (budget − committed cost basis of the held book) into the top-ranked
        # affordable names, each still capped at the per-name target, until the headroom is used
        # or a name ceiling is hit. The real limit becomes the % allocation, not a slot count.
        budget_sizing = (getenv("GREYLINE_MOMENTUM_BUDGET_SIZING", "true") or "true").strip().lower() == "true"
        committed = sum(float(t.get("entry_price") or 0) * abs(float(t.get("quantity") or 0))
                        for t in held_trades)
        deploy_budget = max(0.0, sleeve_budget - committed)
        deploy_budget_start = deploy_budget
        # Safety ceiling so a broad, all-cheap regime can't fragment the book into dust positions.
        max_total_names = int(self.strategy.top_n * float(getenv("GREYLINE_MOMENTUM_MAX_NAMES_MULT", "1.5") or 1.5))

        opened, skipped_risk, skipped_unaffordable = [], 0, 0

        # SECTOR-AWARE, SKIP-AND-CONTINUE. Momentum clusters by sector — today's top picks are
        # heavily semiconductors/AI. The old gate re-checked the exposure limit and BROKE the
        # whole loop the instant any sector hit the cap, which stopped the book from filling
        # into the DIVERSIFYING names further down the list (healthcare, industrials, ...). Now
        # a name whose sector is already at the cap is SKIPPED and the loop continues, so the
        # book fills to top_n across sectors instead of stalling as a small concentrated cluster.
        from os import getenv as _getenv
        from collections import Counter
        from app.services.portfolio_exposure_engine import PortfolioExposureEngine
        _sectorer = PortfolioExposureEngine()
        max_sector_pct = float(_getenv("GREYLINE_MAX_SECTOR_EXPOSURE_PCT", "50"))
        # cap is a count of names per sector, anchored to top_n (unchanged — a tighter fraction
        # when the book floats above top_n, which only helps concentration control)
        max_per_sector = max(1, int(max_sector_pct / 100.0 * self.strategy.top_n))
        sector_count = Counter(_sectorer._sector(s) for s in held)

        for t in targets:
            # STOP conditions differ by sizing mode: budget mode runs until the sleeve headroom
            # is spent (or the name ceiling is hit); legacy mode until the fixed slots are full.
            if budget_sizing:
                if deploy_budget < 1.0:
                    break
                if (len(held) + len(opened)) >= max_total_names:
                    break
            elif len(opened) >= free_slots:
                break
            if t["symbol"] in held:
                continue
            sector = _sectorer._sector(t["symbol"])
            # UNKNOWN is not a real sector — unmapped names must NOT be pooled together and
            # capped as if they were one concentrated bet (that would block legitimate
            # diversification). Only cap named sectors; the map covers 519/557 names.
            if sector != "UNKNOWN" and sector_count[sector] >= max_per_sector:
                skipped_risk += 1          # sector full — skip THIS name, try the next
                continue
            px = t.get("last_close") or 0
            # WHOLE-SHARE sizing — this is exactly what books at TradeStation. Fractional
            # shares cannot be booked there, so recording a fraction here would create a
            # ledger position the broker never holds (a phantom the Reality Guard rightly
            # flags as fantasy). In BUDGET mode a name is sized at the per-name target but never
            # more than the remaining headroom; in legacy mode at the flat per-name budget.
            # Either way a name that can't afford ONE whole share is skipped honestly.
            alloc = min(per_name, deploy_budget) if budget_sizing else per_name
            qty = int(alloc / px) if px > 0 else 0
            if qty <= 0:
                skipped_unaffordable += 1
                continue
            # ENTRY RISK: stamp the ATR + the doctrine's initial stop (the SAME ones the exit manager
            # will manage to) so the edge court measures return on the ACTUAL intended risk, not a 12%
            # proxy. Best-effort — a missing ATR just leaves them None and the court falls back.
            entry_atr = entry_stop = None
            try:
                from app.services.momentum_exit_manager_engine import atr_for
                from app.services.trade_doctrine_engine import TradeDoctrineEngine
                _atr = atr_for(t["symbol"])
                if _atr:
                    _dir = "LONG" if t["side"] == "BUY" else "SHORT"
                    _plan = TradeDoctrineEngine().exit_plan(px, _dir, _atr)
                    entry_atr = round(float(_atr), 6)
                    entry_stop = (_plan or {}).get("initial_stop")
            except Exception:
                entry_atr = entry_stop = None
            self.ledger.open_trade(
                symbol=t["symbol"], side=t["side"], quantity=qty, entry_price=px,
                directional_bias=t["directional_bias"], trade_intent=self.TRADE_INTENT,
                direction_confidence=t["conviction"], entry_atr=entry_atr, entry_stop=entry_stop,
            )
            opened.append({"symbol": t["symbol"], "side": t["side"], "quantity": qty, "entry_price": px})
            sector_count[sector] += 1
            if budget_sizing:
                deploy_budget -= qty * px   # decrement the sleeve headroom by what we actually spent

        # Mirror the decided opens into the TradeStation SIM account as real paper orders,
        # sized whole-share to the $10k book. No-op unless GREYLINE_SIM_BOOKING_ENABLED=true.
        # Best-effort: a SIM/broker hiccup must never break the (validated) decision path.
        sim_booking = {"status": "SIM_BOOKING_DISABLED", "placed": 0}
        try:
            from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
            sim_booking = GreyLineSimExecutionEngine().book_opens(opened, per_name)
        except Exception as e:
            sim_booking = {"status": "SIM_BOOKING_ERROR", "error": str(e)[:200], "placed": 0}

        # RECONCILER (place_order body-verification): the ledger recorded each open ABOVE, but a SIM
        # order can be REJECTED (place_order now reports ok=False from the response body). Void any
        # open leg the broker did NOT confirm, so a rejected order can't sit as a phantom position.
        # Only runs on a clean SIM_BOOKED result (per-leg ok known); on DISABLED/ERROR the ledger
        # stands alone (nothing to reconcile against). Best-effort — never breaks the decision path.
        voided = []
        try:
            if sim_booking.get("status") == "SIM_BOOKED":
                booked_ok = {str(b.get("symbol")).upper() for b in (sim_booking.get("booked") or [])
                             if b.get("ok")}
                for leg in opened:
                    sym = str(leg.get("symbol")).upper()
                    if sym not in booked_ok:
                        v = self.ledger.void_latest(sym, reason="SIM booking rejected/unconfirmed")
                        if v.get("voided"):
                            voided.append(sym)
                if voided:
                    opened = [l for l in opened if str(l.get("symbol")).upper() not in set(voided)]
        except Exception:
            pass

        self._save_state({
            "last_rebalance_at": now.isoformat(), "as_of": asof, "data_source": source,
            "held_before": len(held), "free_slots": free_slots, "opened": len(opened),
            "sizing_mode": "budget" if budget_sizing else "count",
            "sleeve_budget_usd": round(sleeve_budget, 2), "committed_usd": round(committed, 2),
            "deploy_budget_usd": round(deploy_budget_start, 2),
            "sim_placed": sim_booking.get("placed", 0), "sim_status": sim_booking.get("status"),
            "sim_voided_rejects": len(voided),
        })
        return self._result("REBALANCE_COMPLETE", rebalanced=True, as_of=asof, data_source=source,
                            held_before=len(held), free_slots=free_slots, opened=opened,
                            sizing_mode="budget" if budget_sizing else "count",
                            sleeve_budget_usd=round(sleeve_budget, 2),
                            committed_usd=round(committed, 2),
                            deploy_budget_usd=round(deploy_budget_start, 2),
                            skipped_for_risk=skipped_risk,
                            skipped_unaffordable_whole_share=skipped_unaffordable,
                            regime=regime, regime_blocked=len(regime_dropped), long_only=True,
                            vol_blocked=len(vol_dropped), vol_blocked_names=vol_dropped[:10],
                            trash_discarded=len(trash_discarded),
                            trash_discarded_names=[{"symbol": t.get("symbol"),
                                                    "reason": t.get("discard_reason")} for t in trash_discarded[:10]],
                            sim_booking=sim_booking)

    def status(self):
        return self._result("REBALANCE_STATUS_READY", rebalanced=False, **self._state())
