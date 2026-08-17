"""Pre-open readiness audit — verify every link in tomorrow's open chain, read-only.

The night-before question is "will the open go cleanly, or is something silently misconfigured?"
This walks the whole chain — reset armed, capital params sane, every armed strategy path executes,
the data feeds are fresh and reachable, the mission accounting reads true, and the reality guard is
clean — and returns a PASS/WARN/FAIL per check. It never trades and never changes state; it only
looks, so it is safe to run as many times as wanted before the open.
"""

import time as _clock
from datetime import datetime, timedelta
from os import getenv
from pathlib import Path


# READ-THROUGH CACHE for the readiness audit. The audit walks ~20 live TS/UW reads; computed in
# isolation it's ~3s, but when the OPERATOR ROUTE runs it synchronously it contends with the scheduler's
# own TS/UW reads → throttling + retry-backoff → 30-50s (the GO/NO-GO gate effectively times out). This is
# a DISPLAY of a decision, so it follows the house rule "engines decide (in the scheduler), displays render
# (serve cache)". The scheduler recomputes it fresh each cycle; the route serves the cached result with an
# age label. Config/flag/data-freshness readiness doesn't change second-to-second, so a ≤TTL-old read is
# fine for the gate — and it's never fabricated (only a real prior compute is cached).
_AUDIT_CACHE = {"at": 0.0, "result": None}


def _audit_ttl():
    try:
        return float(getenv("GREYLINE_READINESS_CACHE_TTL_S", "150") or 150)
    except (TypeError, ValueError):
        return 150.0


class PreOpenReadinessEngine:

    HIST = Path("app/data/historical")
    CYCLE_COST_HISTORY = Path("app/data/scheduler/cycle_cost_history.jsonl")
    SCHEDULER_FRESH_SECONDS = 1200          # ~3-4 cycles; a recent persisted cycle proves the live scheduler runs

    @classmethod
    def _scheduler_alive_cross_process(cls):
        """Cross-process scheduler liveness: age of the last cycle from the scheduler's OWN persisted output
        (cycle_cost_history). thread_alive is process-local — false when this audit runs outside the service
        — so a recent COMPLETE persisted cycle is the honest, process-independent proof. Returns (alive, detail)."""
        try:
            import json as _json
            lines = [l for l in cls.CYCLE_COST_HISTORY.read_text().splitlines() if l.strip()]
            if not lines:
                return (False, "no persisted cycle history")
            d = _json.loads(lines[-1])
            ts = d.get("timestamp")
            if not ts:
                return (False, "last cycle row has no timestamp")
            age = (datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds()
            ok = age <= cls.SCHEDULER_FRESH_SECONDS and str(d.get("status", "")).upper().endswith("COMPLETE")
            return (ok, "last persisted cycle %.1f min ago (%s)" % (age / 60.0, d.get("status")))
        except Exception as e:
            return (False, "cycle-history read failed: %s" % (repr(e)[:60]))
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

    def audit(self, allow_cache=True):
        """Serve a recent cached audit to operator routes; recompute fresh when stale or forced.

        allow_cache=True (routes): return the last computed audit if younger than the TTL — instant, never
        the 30-50s live recompute under scheduler contention. allow_cache=False (scheduler/reports): always
        recompute and refresh the cache, so the route's cached value stays warm. Only a real, fully-computed
        audit is ever cached (no fabrication)."""
        ttl = _audit_ttl()
        if allow_cache and ttl > 0 and _AUDIT_CACHE["result"] is not None:
            age = _clock.monotonic() - _AUDIT_CACHE["at"]
            if age < ttl:
                out = dict(_AUDIT_CACHE["result"])
                out["served_from_cache"] = True
                out["cache_age_seconds"] = round(age, 1)
                return out
        result = self._compute_audit()
        if ttl > 0:
            _AUDIT_CACHE["at"] = _clock.monotonic()
            _AUDIT_CACHE["result"] = result
        return result

    def _compute_audit(self):
        # Load .env FIRST so every check reads the real configured flags/capital base. Without this a
        # fresh-process caller (a CLI run, a test, a cron) reads the strategy/capital env as unset until
        # some engine happens to reload it mid-audit — making the early flag/capital checks disagree with
        # the later ones. The live service already loads .env at startup, so this is idempotent there.
        try:
            from app.services.env_reload import reload_env
            reload_env()
        except Exception:
            pass

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

        # 6. armed strategy paths surface a decision without throwing (READ-ONLY — never books). Covers
        # ALL SIX sleeves: momentum/vrp/earnings read their (scheduler-populated) decision caches; carry/
        # trend/tbill dry-plan. None of these can place an order, so this is safe on the live route too.
        for name, fn in [("momentum", self._probe_momentum), ("vrp", self._probe_vrp),
                         ("earnings", self._probe_earnings), ("carry", self._probe_carry),
                         ("trend", self._probe_trend), ("tbill", self._probe_tbill)]:
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
            if not g.get("reads_ok", True):
                # A degraded broker read means the mission equity/deployed figures are UNKNOWN, not
                # clean — don't PASS mission accounting the night before an open on a read that failed.
                add("mission_accounting", "WARN",
                    "broker read degraded — mission equity/deployed unavailable; accounting UNVERIFIED")
            else:
                add("mission_accounting", "PASS",
                    f"equity {g['mission_equity']} | deployed {g['deployed']} ({g['deployed_pct']}%) | "
                    f"daily P&L {g['daily_pnl']}")
        except Exception as e:
            add("mission_accounting", "WARN", f"governor error: {repr(e)[:80]}")

        # 9. THE TRADE-FIRING SPINE — the links that decide whether a decided order actually books at the
        # bell: execution authority (the real gate), broker reachability, the SIM fail-closed guard, the
        # order-body verification, scheduler liveness, and the exposure breaker. All read-only.
        self._trade_firing_spine(add)

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

    # ---- six-sleeve decision-surface probes (READ-ONLY, never book) -----------------------------
    def _probe_momentum(self):
        """Momentum reads its scheduler-populated candidate cache + cadence state. NEVER calls
        rebalance() — that path books when due. Mirrors the Opportunity Board's read."""
        import json
        from datetime import date
        from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine as R
        armed = self._flag("GREYLINE_MOMENTUM_ENABLED")
        try:
            c = json.loads(Path("app/data/momentum_reversal/top_candidates_cache.json").read_text())
            n, src, asof = len(c.get("candidates") or []), c.get("data_source"), str(c.get("as_of") or "")[:10]
            surface = f"{n} cached candidate(s), data_source {src} as_of {asof}"
        except Exception:
            surface = "no candidate cache yet (populates on the next scheduler cycle)"
        try:
            st = json.loads(Path("app/data/momentum_reversal/rebalance_state.json").read_text())
            last = date.fromisoformat(str(st.get("last_rebalance_at"))[:10])
            nd = date.fromordinal(last.toordinal() + R.MIN_CALENDAR_DAYS)
            cadence = f"7-day cadence, last {last.isoformat()}, next due {nd.isoformat()}"
        except Exception:
            cadence = "no prior rebalance recorded — would open on the next due cycle"
        return f"{'armed' if armed else 'OFF'}; {surface}; {cadence}"

    def _probe_vrp(self):
        """VRP reads the scheduler-built BestCondors cache (buildable condors + any sleeve error) —
        fast + read-only. Avoids a live 200-name chain scan on the audit path."""
        from app.services.best_condors_engine import BestCondorsEngine
        armed = self._flag("GREYLINE_VRP_SHORT_PREMIUM_ENABLED")
        cached = BestCondorsEngine().cached(limit=50)
        vrp = [c for c in (cached.get("condors") or []) if str(c.get("sleeve") or "").upper() == "VRP"]
        err = (cached.get("sleeve_errors") or {}).get("VRP")
        if err:
            raise RuntimeError(f"VRP sleeve error in best_condors: {err}")
        return f"{'armed' if armed else 'OFF'}; {len(vrp)} buildable condor(s) cached off Unusual Whales"

    def _probe_earnings(self):
        """Earnings reads its status() (candidate names + risk usage) — no condor build, no order."""
        from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine
        st = EarningsVolHarvestEngine().status()
        armed = bool(st.get("armed"))
        cands = len(st.get("candidates_now") or [])
        return (f"{'armed' if armed else 'OFF'}; {cands} name(s) reporting within the window; "
                f"{st.get('open_positions', 0)} open, "
                f"${self._num(st.get('open_risk_usd'))}/${self._num(st.get('portfolio_cap_usd'))} risk used")

    @staticmethod
    def _num(v):
        try:
            return f"{float(v):.0f}"
        except (TypeError, ValueError):
            return "?"

    # ---- the trade-firing spine (READ-ONLY; safe on the live /pre-open-readiness route) ----------
    def _trade_firing_spine(self, add):
        from os import getenv as _ge

        # (a) EXECUTION AUTHORITY — the real gate. A paper order fires only when BOTH the governor
        # allows placement AND SIM booking routes it to the broker (paper-on-but-booking-off just
        # fabricates in the local ledger — the EXEC_BOOKING_COHERENT trap).
        try:
            from app.services.execution_governor import ExecutionGovernor
            perm = ExecutionGovernor().evaluate_execution_permission("EXECUTE")
            sim_book = (_ge("GREYLINE_SIM_BOOKING_ENABLED", "") or "").strip().lower() == "true"
            can_place = bool(perm.get("order_placement_allowed"))
            paper = bool(perm.get("paper_execution_enabled"))
            live_off = not bool(perm.get("live_order_placement_allowed"))
            if can_place and sim_book:
                add("execution_authority", "PASS",
                    f"paper execution ARMED + SIM booking ON → orders WILL book to the Paper account "
                    f"(mode {perm.get('execution_mode')}; live placement OFF={live_off}, as intended)")
            elif can_place and not sim_book:
                add("execution_authority", "FAIL",
                    "paper execution ON but GREYLINE_SIM_BOOKING_ENABLED is OFF → decided orders would "
                    "only fabricate in the local ledger, never reach the broker (EXEC_BOOKING_COHERENT trap)")
            elif paper and not can_place:
                add("execution_authority", "WARN",
                    f"paper flagged on but order_placement_allowed is False: {perm.get('status')}")
            else:
                add("execution_authority", "FAIL",
                    f"execution DISABLED → nothing books at the bell (status {perm.get('status')}, "
                    f"paper={paper}, order_placement_allowed={can_place})")
        except Exception as e:
            add("execution_authority", "FAIL", f"execution governor threw: {repr(e)[:80]}")

        # (b) BROKER CONNECTIVITY — token read + account resolves to SIM + balances/positions/orders read.
        try:
            from app.services.tradestation_token_status_engine import TradeStationTokenStatusEngine
            from app.services.tradestation_account_source_engine import TradeStationAccountSourceEngine
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            tok = TradeStationTokenStatusEngine().evaluate()
            src = TradeStationAccountSourceEngine().resolve()
            view = BrokerAccountViewEngine().snapshot()
            tok_ok, src_ok, reads_ok = (bool(tok.get("ready_for_read_only")),
                                        bool(src.get("ok")), bool(view.get("reads_ok")))
            if tok_ok and src_ok and reads_ok:
                add("broker_connectivity", "PASS",
                    f"token ready (read-only), account {src.get('label')} [{src.get('mode')}] resolved, "
                    f"balances/positions/orders read OK ({len(view.get('positions') or [])} live position(s))")
            else:
                bad = []
                if not tok_ok:
                    bad.append(f"token {tok.get('status')}")
                if not src_ok:
                    bad.append(f"account source unresolved ({src.get('error')})")
                if not reads_ok:
                    bad.append("broker reads degraded (" + (view.get("read_detail") or view.get("status") or "")
                               + (" — TradeStation server error, broker-side" if view.get("read_broker_side") else "") + ")")
                # A degraded READ with a healthy token+source is a transient broker-side blip (the same
                # self-healing class the money tiles / reality guard treat as degraded-not-broken, and
                # snapshot() already bounded-retries before reporting) — WARN like the sibling checks
                # (mission_accounting, exposure_gate), not the loudest pre-open FAIL. Reserve FAIL for a
                # token/source failure that genuinely can't reach the account.
                if tok_ok and src_ok and not reads_ok:
                    add("broker_connectivity", "WARN",
                        "broker reads degraded (transient/self-healing): " + "; ".join(bad))
                else:
                    add("broker_connectivity", "FAIL",
                        "cannot reach the trading account: " + "; ".join(bad))
        except Exception as e:
            add("broker_connectivity", "FAIL", f"broker read threw: {repr(e)[:80]}")

        # (c) SIM FAIL-CLOSED GUARD — booking is structurally incapable of touching the real account.
        try:
            from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
            acct = TradeStationSimBookingEngine()._assert_sim()
            add("sim_booking_target_safe", "PASS",
                f"booking targets SIM account {str(acct)[:3]}*** on the sandbox host — live orders fail-closed")
        except Exception as e:
            add("sim_booking_target_safe", "FAIL",
                f"SIM fail-closed guard tripped (won't book / misconfigured): {repr(e)[:100]}")

        # (d) ORDER-PATH INTEGRITY — success is verified from the BODY (valid OrderID, no Error), NOT
        # HTTP 200. Synthetic payloads only — no network, no order. Proves a rejected order can't be
        # recorded as filled (the naked-short / phantom-position class).
        try:
            from app.services.tradestation_sim_booking_engine import _interpret_order
            ok_s, oid_s, _ = _interpret_order(200, {"Orders": [{"OrderID": "123456"}]})
            ok_r, _, rr = _interpret_order(200, {"Orders": [{"OrderID": "0", "Error": "Insufficient BP"}]})
            ok_e, _, _ = _interpret_order(200, {"Errors": [{"Message": "bad request"}]})
            ok_h, _, _ = _interpret_order(500, {})
            good = (ok_s is True and oid_s == "123456" and ok_r is False and bool(rr)
                    and ok_e is False and ok_h is False)
            add("order_path_integrity", "PASS" if good else "FAIL",
                "order success is verified from the response BODY (valid OrderID, no Error), not HTTP 200 "
                "— a body-level reject can't be recorded as a filled position"
                if good else
                f"BODY-verification guard BROKEN: success={ok_s} reject={ok_r} errors={ok_e} http500={ok_h}")
        except Exception as e:
            add("order_path_integrity", "FAIL", f"order-body verifier threw: {repr(e)[:80]}")

        # (e) SCHEDULER LIVENESS — the cycle that attempts the opens. thread_alive is PROCESS-LOCAL: the
        # running service holds the trading thread, so no-thread-here is unknown-not-down (WARN), never a
        # false FAIL. Healthy = last cycle COMPLETE with no consecutive failures.
        try:
            from app.services.background_scheduler_service import BackgroundSchedulerService
            st = BackgroundSchedulerService.status()
            alive = bool(st.get("thread_alive"))
            consec = int(st.get("consecutive_failures") or 0)
            last = str(st.get("last_status") or "")
            if alive and consec == 0 and last.endswith("COMPLETE"):
                add("scheduler_liveness", "PASS",
                    f"scheduler thread alive; last cycle {last}; success {st.get('cycle_success_rate_pct')}% "
                    f"over {st.get('cycle_count')} cycle(s)")
            elif alive:
                add("scheduler_liveness", "WARN",
                    f"scheduler alive but check the last cycle: last={last or 'n/a'}, "
                    f"consecutive_failures={consec}, last_error={st.get('last_error')}")
            else:
                # thread_alive is PROCESS-LOCAL — false here just means the audit is running OUTSIDE the
                # service. Don't cry wolf: confirm via the scheduler's OWN persisted output (a recent COMPLETE
                # cycle proves the live service's scheduler is running, regardless of which process audits).
                x_alive, x_detail = self._scheduler_alive_cross_process()
                if x_alive:
                    add("scheduler_liveness", "PASS",
                        "scheduler alive (cross-process: %s; thread not in this audit process, which is fine)"
                        % x_detail)
                else:
                    add("scheduler_liveness", "WARN",
                        "no scheduler thread here AND %s — confirm on the live service via "
                        "GET /background-scheduler/status (thread_alive must be True)" % x_detail)
        except Exception as e:
            add("scheduler_liveness", "WARN", f"scheduler status threw: {repr(e)[:80]}")

        # (f) EXPOSURE BREAKER — room to add risk. Now fails CLOSED on a degraded broker read (unknown
        # book blocks new concentration-gated risk). A breach is a legitimate risk-full state, not a fault.
        try:
            from app.services.position_exposure_limit_engine import PositionExposureLimitEngine
            lim = PositionExposureLimitEngine().evaluate()
            if lim.get("limits_ok"):
                add("exposure_gate", "PASS",
                    f"room to add risk: {lim.get('open_position_count')}/{lim.get('max_open_positions')} "
                    f"positions, max sector {lim.get('max_sector_exposure_pct_observed')}%/"
                    f"{lim.get('max_sector_exposure_pct_limit')}%")
            elif lim.get("degraded") or not lim.get("compute_ok"):
                add("exposure_gate", "WARN",
                    f"exposure UNVERIFIABLE (broker read degraded) → breaker fails CLOSED, blocks new "
                    f"concentration-gated risk: {lim.get('status')}")
            else:
                add("exposure_gate", "WARN",
                    f"position/exposure limit BREACHED → no new concentration-gated risk until reduced: "
                    f"{lim.get('breaches')}")
        except Exception as e:
            add("exposure_gate", "WARN", f"exposure limit threw: {repr(e)[:80]}")
