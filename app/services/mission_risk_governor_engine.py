"""Book-level risk governor — the guardrail GreyLine lacked: a DAILY loss limit and a deployment cap.

GreyLine had per-position broker stops and the reality guard, but nothing watching the BOOK as a
whole. With six strategies going live at once on a fresh $10k, the two things that can quietly ruin a
day are (1) the book bleeding past a daily loss limit while everything looks individually fine, and
(2) total deployment creeping over 100% of the mission book. This engine watches both every cycle and
SCREAMS (CRITICAL -> iMessage) the moment either is breached — so a bad day is caught in seconds, on
the phone, not discovered after the close.

On a HALT breach it (1) writes the `opens_halted` marker, (2) alerts CRITICAL -> iMessage. This engine
itself stays read-only on the trading path; the AUTO-HALT is enforced downstream at the single order
choke point — `TradeStationSimBookingEngine.place_order`/`place_multileg` read `opens_halted()` and refuse
OPENING orders while it's set (exits/covers/stops still pass so the book can de-risk), the same
choke-point pattern as the master kill switch. So a -7% day now auto-blocks new opens across EVERY sleeve
without per-engine changes (2026-08-11); it was previously alert-only (the operator had to flip flags by
hand). The marker clears at the next start-of-day baseline.
"""

import json
from datetime import datetime
from os import getenv
from pathlib import Path


class MissionRiskGovernorEngine:

    DIR = Path("app/data/risk")
    SOD = DIR / "sod_equity.json"
    HALT_MARKER = DIR / "opens_halted.json"
    ALERT_STATE = DIR / "governor_alert_state.json"
    IDLE_MARKER = DIR / "armed_idle_since.json"
    POS_COUNT = DIR / "last_position_count.json"   # last non-empty broker read (empty-read sanity)
    POS_COUNT_TRUST_MIN = 90.0                     # trust a recent non-empty count for this long
    THROTTLE_MIN = 30.0

    # "armed but not trading" watch: the failure that sat SILENT on the 2026-07-29 open (strategies
    # were meant to be on, GreyLine ran flat for 90min, and no alert fired because the arming lived in
    # an external task, not the service). Now watched INSIDE the always-on scheduler.
    IDLE_PCT = 5.0             # deployed below this while armed during RTH ...
    IDLE_ALERT_MIN = 20.0      # ... for this long -> CRITICAL alert to the phone
    STRATEGY_FLAGS = ["GREYLINE_VOL_CARRY_ENABLED", "GREYLINE_TREND_ENABLED", "GREYLINE_TBILL_SWEEP_ENABLED",
                      "GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "GREYLINE_EARNINGS_VOL_ENABLED",
                      "GREYLINE_MOMENTUM_ENABLED"]

    @classmethod
    def _armed(cls):
        return [f for f in cls.STRATEGY_FLAGS if (getenv(f, "") or "").strip().lower() == "true"]

    def _is_rth(self):
        try:
            from app.services.market_hours_engine import MarketHoursEngine
            return MarketHoursEngine().status().get("is_regular_session") is True
        except Exception:
            return False

    def reset_sod(self, equity=None):
        """Reset start-of-day equity — call after a rebaseline so daily P&L isn't a reset artifact."""
        if equity is None:
            equity, _, _ = self._equity_and_deployed()
        self.DIR.mkdir(parents=True, exist_ok=True)
        self.SOD.write_text(json.dumps({"date": datetime.utcnow().date().isoformat(), "equity": equity}))
        return equity

    def _idle_since(self):
        today = datetime.utcnow().date().isoformat()
        try:
            rec = json.loads(self.IDLE_MARKER.read_text())
            if rec.get("date") == today and rec.get("since"):
                return datetime.fromisoformat(rec["since"])
        except Exception:
            pass
        now = datetime.utcnow()
        self.DIR.mkdir(parents=True, exist_ok=True)
        self.IDLE_MARKER.write_text(json.dumps({"date": today, "since": now.isoformat()}))
        return now

    def _clear_idle(self):
        try:
            self.IDLE_MARKER.unlink()
        except Exception:
            pass

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _base(cls):
        try:
            return float(getenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "10000") or 10000)
        except (TypeError, ValueError):
            return 10000.0

    @classmethod
    def _warn_pct(cls):
        try:
            return abs(float(getenv("GREYLINE_DAILY_LOSS_WARN_PCT", "") or 4.0))
        except (TypeError, ValueError):
            return 4.0

    @classmethod
    def _halt_pct(cls):
        try:
            return abs(float(getenv("GREYLINE_DAILY_LOSS_HALT_PCT", "") or 7.0))
        except (TypeError, ValueError):
            return 7.0

    # ---- mission figures (read-only) -----------------------------------------------------------

    def _equity_and_deployed(self):
        base = self._base()
        try:
            from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine
            realized = MissionRealizedPnlEngine().cumulative_realized()
        except Exception:
            realized = 0.0
        deployed, unrealized, reads_ok = 0.0, 0.0, False
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            snap = BrokerAccountViewEngine().snapshot()
            reads_ok = bool(snap.get("reads_ok", True))   # False = broker read failed this cycle
            rows = snap.get("positions", []) or []
            unrealized = sum(self._f(r.get("unrealized_pnl")) for r in rows)
            # DEPLOYED = at-risk capital only. Exclude the T-bill sweep (SGOV) — it's a cash-equivalent
            # parking lot, not deployed risk; counting it would inflate deployed_pct after the sweep and
            # (harmlessly) skew the idle/over-deploy checks. Matches /account-summary's deployed figure.
            from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine
            _tb = TbillCashSweepEngine.symbol()
            deployed = sum(self._f(r.get("entry_price")) * self._f(r.get("quantity")) for r in rows
                           if ((str(r.get("symbol") or "").split() or [""])[0]).upper() != _tb)
            # EMPTY-READ SANITY: a 200 with an EMPTY positions array can be a transient glitch, not a
            # genuinely flat book. If we just saw positions and now see none, treat the read as SUSPECT
            # (reads_ok False) so a real drawdown can't read as ~flat (unrealized 0) and skip the halt.
            if rows:
                self._record_position_count(len(rows))
            elif reads_ok and self._recent_position_count() > 0:
                reads_ok = False   # empty-but-recently-nonempty -> don't trust; skip loss/idle checks
        except Exception:
            reads_ok = False
        return round(base + realized + unrealized, 2), round(deployed, 2), reads_ok

    def _record_position_count(self, n):
        try:
            self.DIR.mkdir(parents=True, exist_ok=True)
            self.POS_COUNT.write_text(json.dumps({"count": int(n), "at": datetime.utcnow().isoformat()}))
        except Exception:
            pass

    def _recent_position_count(self):
        """Last non-empty broker position count, but only if recorded recently (else 0 — a genuine
        flatten ages out, so an intentionally-empty book eventually reads as trusted-empty)."""
        try:
            rec = json.loads(self.POS_COUNT.read_text())
            age = (datetime.utcnow() - datetime.fromisoformat(rec["at"])).total_seconds() / 60.0
            return int(rec.get("count", 0)) if age <= self.POS_COUNT_TRUST_MIN else 0
        except Exception:
            return 0

    def _sod_equity(self, current, persist=True):
        """Start-of-day mission equity; recorded on the first read of each UTC day. `persist=False`
        (a degraded broker read) returns the value transiently WITHOUT writing it, so a bad first
        read of the day can't poison the daily-loss baseline — the next clean read records the SOD."""
        today = datetime.utcnow().date().isoformat()
        try:
            rec = json.loads(self.SOD.read_text())
            if rec.get("date") == today:
                return self._f(rec.get("equity"))
        except Exception:
            pass
        if not persist:
            return current
        self.DIR.mkdir(parents=True, exist_ok=True)
        self.SOD.write_text(json.dumps({"date": today, "equity": current}))
        return current

    def opens_halted(self):
        today = datetime.utcnow().date().isoformat()
        try:
            return json.loads(self.HALT_MARKER.read_text()).get("date") == today
        except Exception:
            return False

    def snapshot(self):
        base = self._base()
        equity, deployed, reads_ok = self._equity_and_deployed()
        # Don't let a DEGRADED read write the start-of-day baseline: a missing-unrealized equity
        # persisted as SOD would skew the -4%/-7% daily-loss ladder all day. On a bad read, return
        # the transient value WITHOUT persisting; the next clean read of the day records the real SOD.
        sod = self._sod_equity(equity, persist=reads_ok)
        daily = round(equity - sod, 2)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "mission_equity": equity, "start_of_day_equity": sod, "reads_ok": reads_ok,
            "daily_pnl": daily, "daily_pnl_pct": round(100 * daily / base, 2) if base else 0.0,
            "deployed": deployed, "deployed_pct": round(100 * deployed / base, 2) if base else 0.0,
            "warn_at_pct": -self._warn_pct(), "halt_at_pct": -self._halt_pct(),
            "halted": self.opens_halted(), "status": "MISSION_RISK_GOVERNOR",
        }

    # ---- alerting (throttled) ------------------------------------------------------------------

    def _throttled(self, key):
        try:
            prev = json.loads(self.ALERT_STATE.read_text()).get(key)
            if prev:
                age = (datetime.utcnow() - datetime.fromisoformat(prev)).total_seconds() / 60.0
                return age < self.THROTTLE_MIN
        except Exception:
            pass
        return False

    def _mark(self, key):
        try:
            self.DIR.mkdir(parents=True, exist_ok=True)
            state = {}
            try:
                state = json.loads(self.ALERT_STATE.read_text())
            except Exception:
                state = {}
            state[key] = datetime.utcnow().isoformat()
            self.ALERT_STATE.write_text(json.dumps(state))
        except Exception:
            pass

    def _alert(self, key, title, message, severity):
        if self._throttled(key):
            return False
        try:
            from app.services.operator_notification_engine import OperatorNotificationEngine
            OperatorNotificationEngine().record(event_type=key, title=title, message=message,
                                                severity=severity, source="MISSION_RISK_GOVERNOR")
        except Exception:
            pass
        self._mark(key)
        return True

    def check_and_alert(self):
        s = self.snapshot()
        base = self._base()
        alerts = []
        # If the broker account couldn't be read this cycle, deployed/unrealized are UNKNOWN (not
        # zero). Acting on a failed read as if it were zero would false-fire a CRITICAL "armed but
        # NOT trading" or "past HALT loss limit" mid-open — the operator chases a phantom. Skip the
        # loss-ladder + over-deploy + idle checks entirely; a persistent read failure is caught by
        # the scheduler-cycle-health alert + reality guard, not by treating unknown as zero.
        if not s.get("reads_ok", True):
            return {**s, "armed_count": len(self._armed()), "armed_idle": False,
                    "alerts_fired": [], "skipped": "broker_read_degraded"}
        # daily loss ladder
        if s["daily_pnl"] <= -self._halt_pct() / 100.0 * base:
            self.DIR.mkdir(parents=True, exist_ok=True)
            self.HALT_MARKER.write_text(json.dumps({"date": datetime.utcnow().date().isoformat(),
                                                    "daily_pnl": s["daily_pnl"]}))
            # The message must not send the operator to the strategy flags. New opens are ALREADY
            # auto-blocked by the marker written just above (the booking choke point reads it), and
            # flipping GREYLINE_*_ENABLED=false ALSO stops each sleeve's run_cycle — which is what
            # manages and EXITS open positions. On a halt day that would freeze the book into its
            # losers instead of letting it de-risk. Say what already happened, not a stale manual step.
            if self._alert("BOOK_DAILY_LOSS_HALT", "Mission book past HALT loss limit",
                           f"Book down {s['daily_pnl']} today ({s['daily_pnl_pct']}%), past the "
                           f"{-self._halt_pct()}% halt limit. New opens are AUTO-BLOCKED across every "
                           f"sleeve at the order choke point; exits/covers/stops still pass so the book "
                           f"can de-risk. Clears at the next start-of-day. Do NOT flip the strategy "
                           f"flags to false — that also stops the sleeves EXITING open positions. To "
                           f"stop everything, use the master switch "
                           f"(GREYLINE_PAPER_EXECUTION_ENABLED=false), which also keeps exits open.",
                           "CRITICAL"):
                alerts.append("HALT")
        elif s["daily_pnl"] <= -self._warn_pct() / 100.0 * base:
            if self._alert("BOOK_DAILY_LOSS_WARN", "Mission book daily loss warning",
                           f"Book down {s['daily_pnl']} today ({s['daily_pnl_pct']}%), past the "
                           f"{-self._warn_pct()}% warning line. Watching.", "WARNING"):
                alerts.append("WARN")
        # over-deployment
        if s["deployed_pct"] > 100.0:
            if self._alert("BOOK_OVER_DEPLOYED", "Mission book OVER-deployed",
                           f"Deployed {s['deployed']} = {s['deployed_pct']}% of the {base:.0f} book "
                           f"(>100%). Capital coordination breached — review allocations.", "CRITICAL"):
                alerts.append("OVER_DEPLOYED")

        # ARMED BUT NOT TRADING — the silent open-day failure, now self-watched in the always-on
        # service. Strategies enabled + market open + deployed ~nothing for too long = likely idle.
        armed = self._armed()
        idle = bool(armed and self._is_rth() and s["deployed_pct"] < self.IDLE_PCT)
        if idle:
            mins = (datetime.utcnow() - self._idle_since()).total_seconds() / 60.0
            if mins >= self.IDLE_ALERT_MIN and self._alert(
                    "BOOK_ARMED_BUT_IDLE", "GreyLine armed but NOT trading",
                    f"{len(armed)} strateg(ies) enabled and the market is open, but deployed is only "
                    f"{s['deployed_pct']}% for ~{round(mins)}min. GreyLine is likely UP but idle — "
                    f"check the scheduler cycle and strategy flags NOW.", "CRITICAL"):
                alerts.append("ARMED_IDLE")
        else:
            self._clear_idle()
        return {**s, "armed_count": len(armed), "armed_idle": idle, "alerts_fired": alerts}
