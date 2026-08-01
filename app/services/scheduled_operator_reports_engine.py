"""Scheduled operator self-reports — the always-on service tells YOU what's happening, so knowing
the open went cleanly never depends on you (or an assistant) remembering to check.

Two time-gated, once-per-day iMessages, driven from inside the background scheduler cycle:

  * PRE-OPEN PAGER (~9:20-9:31 ET): runs the pre-open readiness audit. If NOT READY it fires a
    CRITICAL alert listing the failing checks — the direct antidote to the 2026-07-29 silent open
    (strategies never armed, no alert, sat idle 90min). If READY it sends a short INFO green-light,
    so you get a daily proof-of-life that the monitor itself is alive.
  * POST-CLOSE REPORT (~16:00-16:20 ET): an INFO summary of the day — mission equity, daily P&L,
    at-risk deployment, cash, open positions, and any governor alerts fired — so you always know
    what happened without asking.

Everything is best-effort and wrapped: a failure here can never affect trading (it runs after all
sleeves) and never throws into the cycle.
"""

import json
from datetime import datetime
from pathlib import Path


class ScheduledOperatorReportsEngine:

    DIR = Path("app/data/operator_reports")
    PAGER_MARKER = DIR / "pre_open_pager_last.json"
    REPORT_MARKER = DIR / "post_close_report_last.json"

    # ET minutes-of-day windows (hour*60 + minute). Wide enough that a ~5-min cycle lands in them.
    PRE_OPEN_START, PRE_OPEN_END = 9 * 60 + 20, 9 * 60 + 31     # 09:20–09:31 ET
    POST_CLOSE_START, POST_CLOSE_END = 16 * 60 + 0, 16 * 60 + 20  # 16:00–16:20 ET

    @staticmethod
    def _et_now(market_hours):
        try:
            return datetime.fromisoformat(str(market_hours.get("market_time")))
        except Exception:
            return None

    @classmethod
    def _fired_today(cls, marker, today):
        try:
            return json.loads(marker.read_text()).get("date") == today
        except Exception:
            return False

    @classmethod
    def _mark(cls, marker, today):
        try:
            cls.DIR.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"date": today, "at": datetime.utcnow().isoformat()}))
        except Exception:
            pass

    @staticmethod
    def _dispatch(title, message, severity, fingerprint):
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return {"sent": False, "reason": "no external channel"}
            eng.dispatch(title=title, message=message, severity=severity,
                         fingerprint=fingerprint, force=True)   # force: a daily report must not be throttled
            return {"sent": True, "title": title}
        except Exception as e:
            return {"sent": False, "error": repr(e)[:120]}

    # ---- the two reports ----------------------------------------------------------------------

    @staticmethod
    def _earnings_readiness_line():
        """One-line earnings fire-readiness for the pre-open pager (READ-ONLY). The earnings sleeve is
        the fastest to feed the edge court, so surface whether it will actually fire today."""
        try:
            from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine
            fr = EarningsVolHarvestEngine().fire_readiness()
            rd = ", ".join(fr.get("report_dates") or []) or "—"
            if fr.get("will_fire"):
                return f" Earnings: WILL FIRE (reporters {rd})."
            return f" Earnings: will NOT fire — {str(fr.get('verdict') or '')[:70]}."
        except Exception:
            return ""

    @staticmethod
    def _earnings_activity_line():
        """One-line earnings activity for the post-close report (READ-ONLY): did it round-trip into the
        edge court today? Reports open condors + the premium_earnings realized-trade count."""
        try:
            from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine
            from app.services.edge_persistence_engine import EdgePersistenceEngine
            opn = EarningsVolHarvestEngine().status().get("open_positions", 0)
            pe = (EdgePersistenceEngine().realized_edge().get("sleeves") or {}).get("premium_earnings") or {}
            trades = pe.get("trades", 0)
            return (f" Earnings: {opn} open condor(s); edge court has {trades} premium_earnings "
                    f"trade(s) toward the 20-trade gate.")
        except Exception:
            return ""

    @classmethod
    def _pre_open_pager(cls, today):
        try:
            from app.services.pre_open_readiness_engine import PreOpenReadinessEngine
            audit = PreOpenReadinessEngine().audit()
        except Exception as e:
            return cls._dispatch("GreyLine pre-open audit FAILED to run",
                                 f"Could not evaluate readiness before the open: {repr(e)[:120]}. "
                                 "Check the service NOW.", "CRITICAL", f"PREOPEN_AUDIT_ERR:{today}")
        overall = audit.get("overall")
        if overall == "READY":
            return cls._dispatch(
                "GreyLine READY for the open",
                f"Pre-open audit PASSED ({audit.get('fail_count', 0)} fails / "
                f"{audit.get('warn_count', 0)} warns). Armed and green for the {today} open."
                + cls._earnings_readiness_line(),
                "INFO", f"PREOPEN_READY:{today}")
        fails = [c for c in (audit.get("checks") or []) if c.get("status") == "FAIL"]
        detail = "; ".join(f"{c.get('check')}: {str(c.get('detail'))[:60]}" for c in fails[:6]) or "see /pre-open-readiness"
        return cls._dispatch(
            "GreyLine NOT READY for the open",
            f"Pre-open audit = {overall}, {audit.get('fail_count')} FAIL. The open may not fire "
            f"cleanly. FAILING: {detail}. Fix NOW." + cls._earnings_readiness_line(),
            "CRITICAL", f"PREOPEN_NOTREADY:{today}")

    @classmethod
    def _post_close_report(cls, today):
        eq = dep = dep_pct = cash = daily_pct = None
        alerts = open_positions = None
        failed = []
        try:
            from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
            s = MissionRiskGovernorEngine().snapshot()
            if not s.get("reads_ok", True):
                failed.append("mission governor (broker read degraded)")
            eq, dep_pct, daily_pct = s.get("mission_equity"), s.get("deployed_pct"), s.get("daily_pnl_pct")
            dep = s.get("deployed")
        except Exception as e:
            failed.append(f"mission governor ({repr(e)[:60]})")
        try:
            from app.routes.account_summary import account_summary
            a = account_summary()
            if a.get("degraded"):
                failed.append("account summary (degraded read)")
            cash, open_positions = a.get("cash_on_hand"), a.get("open_position_count")
        except Exception as e:
            failed.append(f"account summary ({repr(e)[:60]})")

        # A failed/degraded read must NOT go out as a calm INFO with "$None" — that presents a broken
        # accounting pipeline as a healthy green report. Surface it as a DEGRADED alert naming exactly
        # what couldn't be read so a silent close-of-day accounting outage is visible.
        if failed or eq is None:
            detail = "; ".join(failed) or "mission equity unavailable"
            return cls._dispatch(
                "GreyLine daily close report — DEGRADED",
                f"Close {today}: daily accounting is INCOMPLETE — could not read {detail}. "
                "Check /account-summary and /background-scheduler/status.",
                "WARNING", f"POSTCLOSE:{today}")

        msg = (f"Close {today}: equity ${eq}, daily P&L {daily_pct}%. At-risk deployed "
               f"${dep} ({dep_pct}%), cash ${cash}, {open_positions} open position(s)."
               + cls._earnings_activity_line() +
               " Sleeves ran their normal cycle; see /background-scheduler/status for detail.")
        return cls._dispatch("GreyLine daily close report", msg, "INFO", f"POSTCLOSE:{today}")

    # ---- entry point (called each scheduler cycle) --------------------------------------------

    @classmethod
    def run(cls, market_hours):
        try:
            et = cls._et_now(market_hours)
            if et is None:
                return {"status": "SCHEDULED_REPORTS_NO_ET_TIME"}
            # only on trading days
            if str(market_hours.get("is_weekday")) != "True" or str(market_hours.get("is_holiday")) == "True":
                return {"status": "SCHEDULED_REPORTS_NOT_TRADING_DAY"}
            hm = et.hour * 60 + et.minute
            today = et.date().isoformat()
            out = {}
            if cls.PRE_OPEN_START <= hm <= cls.PRE_OPEN_END and not cls._fired_today(cls.PAGER_MARKER, today):
                out["pager"] = cls._pre_open_pager(today)
                cls._mark(cls.PAGER_MARKER, today)
            if cls.POST_CLOSE_START <= hm <= cls.POST_CLOSE_END and not cls._fired_today(cls.REPORT_MARKER, today):
                out["report"] = cls._post_close_report(today)
                cls._mark(cls.REPORT_MARKER, today)
            return {"status": "SCHEDULED_REPORTS", "et_minute": hm, **out}
        except Exception as e:
            return {"status": "SCHEDULED_REPORTS_DEGRADED", "error": repr(e)[:150]}

    @classmethod
    def preview(cls):
        """On-demand: what the two reports WOULD say right now (does not send / does not gate)."""
        today = datetime.utcnow().date().isoformat()
        try:
            from app.services.pre_open_readiness_engine import PreOpenReadinessEngine
            audit = PreOpenReadinessEngine().audit()
        except Exception as e:
            audit = {"overall": "ERROR", "error": repr(e)[:120]}
        return {"timestamp": datetime.utcnow().isoformat(),
                "pre_open_readiness": {"overall": audit.get("overall"),
                                       "fail_count": audit.get("fail_count"),
                                       "warn_count": audit.get("warn_count")},
                "earnings_pager_line": cls._earnings_readiness_line().strip(),
                "earnings_postclose_line": cls._earnings_activity_line().strip(),
                "windows_et": {"pre_open": "09:20-09:31", "post_close": "16:00-16:20"},
                "status": "SCHEDULED_REPORTS_PREVIEW"}
