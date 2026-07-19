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
    GROSS_TARGET = 0.75           # deploy ~75% of capital across top-N
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

        targets, _ = self.strategy.select(series)

        # Exits are owned by MomentumExitManagerEngine (validated H2 doctrine), NOT the
        # rebalance. So the rebalance no longer closes the book — it only TOPS UP: fills
        # empty slots (top_n minus what's still open) with the strongest fresh signals not
        # already held. Positions leave the book when H2 stops or fully scales them out.
        trades = self.ledger._read_all()
        held = {t.get("symbol") for t in trades
                if t.get("status") == "OPEN" and t.get("trade_intent") == self.TRADE_INTENT}
        free_slots = max(0, self.strategy.top_n - len(held))

        per_name = (self.strategy.capital_base * self.GROSS_TARGET) / max(1, self.strategy.top_n)
        opened, skipped_risk = [], 0
        for t in targets:
            if len(opened) >= free_slots:
                break
            if t["symbol"] in held:
                continue
            if not PositionExposureLimitEngine().evaluate().get("limits_ok", False):
                skipped_risk = free_slots - len(opened)
                break
            px = t.get("last_close") or 0
            qty = round(per_name / px, 4) if px > 0 else 0
            if qty <= 0:
                continue
            self.ledger.open_trade(
                symbol=t["symbol"], side=t["side"], quantity=qty, entry_price=px,
                directional_bias=t["directional_bias"], trade_intent=self.TRADE_INTENT,
                direction_confidence=t["conviction"],
            )
            opened.append({"symbol": t["symbol"], "side": t["side"], "quantity": qty, "entry_price": px})

        # Mirror the decided opens into the TradeStation SIM account as real paper orders,
        # sized whole-share to the $10k book. No-op unless GREYLINE_SIM_BOOKING_ENABLED=true.
        # Best-effort: a SIM/broker hiccup must never break the (validated) decision path.
        sim_booking = {"status": "SIM_BOOKING_DISABLED", "placed": 0}
        try:
            from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
            sim_booking = GreyLineSimExecutionEngine().book_opens(opened, per_name)
        except Exception as e:
            sim_booking = {"status": "SIM_BOOKING_ERROR", "error": str(e)[:200], "placed": 0}

        self._save_state({
            "last_rebalance_at": now.isoformat(), "as_of": asof, "data_source": source,
            "held_before": len(held), "free_slots": free_slots, "opened": len(opened),
            "sim_placed": sim_booking.get("placed", 0), "sim_status": sim_booking.get("status"),
        })
        return self._result("REBALANCE_COMPLETE", rebalanced=True, as_of=asof, data_source=source,
                            held_before=len(held), free_slots=free_slots, opened=opened,
                            skipped_for_risk=skipped_risk, sim_booking=sim_booking)

    def status(self):
        return self._result("REBALANCE_STATUS_READY", rebalanced=False, **self._state())
