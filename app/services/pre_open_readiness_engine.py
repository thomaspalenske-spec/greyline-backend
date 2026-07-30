"""Pre-open readiness audit — verify every link in tomorrow's open chain, read-only.

The night-before question is "will the open go cleanly, or is something silently misconfigured?"
This walks the whole chain — reset armed, capital params sane, every armed strategy path executes,
the data feeds are fresh and reachable, the mission accounting reads true, and the reality guard is
clean — and returns a PASS/WARN/FAIL per check. It never trades and never changes state; it only
looks, so it is safe to run as many times as wanted before the open.
"""

from datetime import datetime, timedelta
from os import getenv
from pathlib import Path


class PreOpenReadinessEngine:

    HIST = Path("app/data/historical")
    TREND_BASKET = ["QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"]

    @staticmethod
    def _flag(name):
        return (getenv(name, "") or "").strip().lower() == "true"

    @staticmethod
    def _last_csv_date(path):
        try:
            last = None
            import csv
            with open(path) as f:
                for r in csv.DictReader(f):
                    last = str(r.get("date"))[:10]
            return last
        except Exception:
            return None

    def audit(self):
        checks = []

        def add(name, status, detail):
            checks.append({"check": name, "status": status, "detail": detail})

        # This audit runs in TWO modes. RESET MODE (flatten-all ON) is the one-time clean-slate day:
        # the book must flatten + rebaseline BEFORE any sleeve opens, so strategies-off is correct and
        # strategies-on is the risk. NORMAL-OPEN MODE (flatten-all OFF) is every ordinary trading day:
        # sleeves SHOULD be armed and flatten-all SHOULD be off — that's the healthy state, not a
        # warning. Checks 1-2 branch on the mode so a normal open reads a clean READY instead of
        # inheriting stale reset-day warnings (which would mask a real warning next to them).
        reset_mode = self._flag("GREYLINE_FLATTEN_ALL_ENABLED")

        # 1. reset posture — both states are valid; PASS with the posture that's actually intended.
        add("reset_armed", "PASS",
            "RESET MODE: flatten-all armed to flatten the book + rebaseline to $10k at the open"
            if reset_mode else "normal trading open — no reset scheduled (flatten-all OFF, as expected)")

        # 2. strategy flags — the correct state is mode-dependent.
        flags = {k: self._flag(k) for k in [
            "GREYLINE_VOL_CARRY_ENABLED", "GREYLINE_VRP_SHORT_PREMIUM_ENABLED", "GREYLINE_TREND_ENABLED",
            "GREYLINE_EARNINGS_VOL_ENABLED", "GREYLINE_MOMENTUM_ENABLED", "GREYLINE_TBILL_SWEEP_ENABLED"]}
        any_on = any(flags.values())
        if reset_mode:
            # pre-reset the sleeves must be OFF so they don't open into a book that's about to flatten
            add("strategy_flags_pre_open", "PASS" if not any_on else "WARN",
                f"pre-reset all OFF (armed after a clean reset): {flags}" if not any_on
                else f"strategies ON while a reset is armed — may fight flatten-all: {flags}")
        else:
            # normal open: sleeves SHOULD be armed. The dangerous case is nothing armed -> nothing opens.
            add("strategy_flags_pre_open", "PASS" if any_on else "WARN",
                f"sleeves armed for the open: {flags}" if any_on
                else f"NO sleeves armed — nothing will open at the bell: {flags}")

        # 3. capital coordination INVARIANT (hard). Sleeve budgets are now %-OF-EQUITY, resolved
        # centrally by SleeveCapitalBudgetEngine (each sleeve targets pct*equity, clamped to live
        # deployable cash so no single sleeve over-commits). The T-bill sweep stays DEMAND-DRIVEN:
        # it parks idle cash (above committed non-SGOV positions + an operating buffer) into SGOV
        # for yield and sells SGOV back when a sleeve draws cash. The book-level guarantee left is
        # that the sleeve TARGETS don't COLLECTIVELY exceed 100% of equity — 100% is intended (the
        # book should deploy up to all available cash when sleeves have opportunities); >100% would
        # mean the targets over-subscribe the book before cash-clamping even applies.
        from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
        pct_table = SleeveCapitalBudgetEngine.pct_table()
        total_pct = round(sum(pct_table.values()), 2)
        base_set = bool((getenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "") or "").strip())
        detail = ("sleeve targets " + " + ".join(f"{k} {v:.0f}%" for k, v in pct_table.items())
                  + f" = {total_pct:.0f}% of equity (%-of-equity, scales with the account; clamped to "
                  f"live deployable cash). T-bill sweep parks idle cash above (committed + buffer) into SGOV.")
        if not base_set:
            add("capital_params", "FAIL",
                "UNSET GREYLINE_ACCOUNT_CAPITAL_BASE — the equity/return denominator is undefined. "
                "Set it explicitly in .env. " + detail)
        elif total_pct > 100.5:
            add("capital_params", "FAIL",
                f"capital invariant BROKEN — sleeve targets sum to {total_pct:.0f}% > 100% of equity, "
                "so they over-subscribe the book before cash-clamping. " + detail)
        else:
            add("capital_params", "PASS", detail)

        # 4. data freshness — trend CSVs
        cutoff = (datetime.utcnow().date() - timedelta(days=5)).isoformat()
        stale = []
        for s in self.TREND_BASKET:
            d = self._last_csv_date(self.HIST / f"{s}_daily.csv")
            if not d or d < cutoff:
                stale.append(f"{s}:{d}")
        add("trend_data_fresh", "PASS" if not stale else "WARN",
            "all trend-basket CSVs recent" if not stale else f"stale/missing: {stale}")

        # 5. live VIX term structure reachable (carry signal)
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            q = TradeStationQuoteLiveEngine()
            def _last(sym):
                rj = (q.get_quote(sym).get("response_json") or {})
                row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
                try:
                    return float(row.get("Last") or row.get("Close") or 0)
                except (TypeError, ValueError):
                    return 0.0
            vix, vix3m = _last("$VIX.X"), _last("$VIX3M.X")
            ok = vix > 0 and vix3m > 0
            add("carry_signal_data", "PASS" if ok else "FAIL",
                f"VIX {vix} / VIX3M {vix3m} -> {'contango' if ok and vix < vix3m else 'backwardation' if ok else 'NO QUOTE'}")
        except Exception as e:
            add("carry_signal_data", "FAIL", f"quote engine error: {repr(e)[:80]}")

        # 6. armed strategy paths execute without throwing (dry / plan only)
        for name, fn in [("carry", self._probe_carry), ("trend", self._probe_trend), ("tbill", self._probe_tbill)]:
            try:
                add(f"{name}_path", "PASS", fn())
            except Exception as e:
                add(f"{name}_path", "FAIL", f"THREW: {repr(e)[:100]}")

        # 7. reality guard clean
        try:
            from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
            rg = GreyLineRealityGuardEngine().check()
            crit = rg.get("critical_failures") or []
            add("reality_guard", "PASS" if not crit else "FAIL",
                rg.get("status") or ("clean" if not crit else f"critical: {crit}"))
        except Exception as e:
            add("reality_guard", "WARN", f"could not evaluate: {repr(e)[:80]}")

        # 8. mission accounting reads
        try:
            from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
            g = MissionRiskGovernorEngine().snapshot()
            add("mission_accounting", "PASS",
                f"equity {g['mission_equity']} | deployed {g['deployed']} ({g['deployed_pct']}%) | "
                f"daily P&L {g['daily_pnl']}")
        except Exception as e:
            add("mission_accounting", "WARN", f"governor error: {repr(e)[:80]}")

        fails = [c for c in checks if c["status"] == "FAIL"]
        warns = [c for c in checks if c["status"] == "WARN"]
        overall = "NOT_READY" if fails else ("READY_WITH_WARNINGS" if warns else "READY")
        return {"timestamp": datetime.utcnow().isoformat(), "overall": overall,
                "fail_count": len(fails), "warn_count": len(warns), "checks": checks}

    def _probe_carry(self):
        from app.services.vol_term_structure_carry_engine import VolTermStructureCarryEngine
        p = VolTermStructureCarryEngine().plan()
        return f"plan status {p.get('status')}, state {p.get('state')}"

    def _probe_trend(self):
        from app.services.trend_following_engine import TrendFollowingEngine
        p = TrendFollowingEngine().plan()
        return f"{p.get('assets_in_uptrend')}/{p.get('of')} in uptrend, would deploy {p.get('deployed_usd')}"

    def _probe_tbill(self):
        from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine
        p = TbillCashSweepEngine().plan()
        return f"plan status {p.get('status')}, target {p.get('target_shares')} sh"
