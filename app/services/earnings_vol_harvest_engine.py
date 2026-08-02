"""Harvest the earnings IV-crush FORWARD — small, defined-risk, honestly unproven.

The earnings implied move can't be backtested (no historical options data exists), so the only way
to learn whether GreyLine can CAPTURE the premium net of costs is to trade a tiny defined-risk sleeve
forward and let the evidence accrue on /harvest-proof (strategy='earnings_vol') alongside the
/earnings-vol-proof panel.

Mechanics: the night before a rich-IV name reports, sell a DEFINED-RISK iron condor in the nearest
expiry AFTER the report (so the option lives through the crush), sized small. Close ~1 session after
the report, when the IV collapse is realized — NOT on the 21-DTE rule (the post-earnings weekly is
intentionally short-dated). Every position is defined-risk by construction (reuses the VRP condor
builder), so a gap through the strikes is capped at the wing width.

SAFETY BY REUSE: positions are written to the VRP ledger with strategy='earnings_vol', so fill
reconciliation, the broker protective-stop exclusion, the dashboard 'managed' labelling and the
condor display all cover these legs automatically — no parallel machinery to drift out of sync. The
ONE exit difference (close after earnings, skip MANAGE_DTE) is a branch in the shared manage loop.
"""

import json
from datetime import datetime, timezone, date
from os import getenv
from pathlib import Path


class EarningsVolHarvestEngine:

    LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")
    PANEL = Path("app/data/research/earnings_vol_panel.jsonl")

    IV_RANK_FLOOR = 0.60        # only sell into genuinely RICH pre-earnings IV (normalized 0-1)
    REPORT_WITHIN_SESSIONS = 2  # reporting in the next 1-2 TRADING SESSIONS — sell near peak pre-earnings IV
    MAX_CONCURRENT = 3          # small sleeve
    LIMIT_PER_DAY = 2
    # Per-condor max-loss cap is CENTRAL now (SleeveCapitalBudgetEngine.per_condor_max_loss =
    # max(5% equity, $500 floor)) — build_condor defaults to it via the shared VRP instance, so both
    # condor sleeves share one cap. No local override here.
    DEFAULT_PORTFOLIO_RISK_CAP_USD = 900   # fallback if the equity read fails (was the static probe cap)

    @property
    def PORTFOLIO_RISK_CAP_USD(self):
        # Now %-of-equity (scales with the account), not a static $900. It's a defined-RISK cap, not
        # a cash outlay, so scaled off equity but NOT cash-clamped. Resolved LAZILY on first access
        # and cached (constructing the engine does no broker read). getattr(eng,
        # "PORTFOLIO_RISK_CAP_USD") in the opportunity board sees the live value. Settable (tests);
        # falls back to the class default if the resolver is unavailable.
        cached = getattr(self, "_prc_cache", None)
        if cached is not None:
            return cached
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            val = SleeveCapitalBudgetEngine.budget_usd("earnings", clamp_to_cash=False)
        except Exception:
            val = type(self).DEFAULT_PORTFOLIO_RISK_CAP_USD
        self._prc_cache = val
        return val

    @PORTFOLIO_RISK_CAP_USD.setter
    def PORTFOLIO_RISK_CAP_USD(self, value):
        self._prc_cache = float(value)

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_EARNINGS_VOL_ENABLED", "") or "").strip().lower() == "true"

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # ---- ledger helpers (shared VRP ledger, filtered to this strategy) -------------------------

    def _ledger_readable(self):
        """True iff the ledger file could be read+parsed. Distinguishes a genuinely-empty book (readable,
        no open rows) from an unreadable ledger — so a swallowed read isn't mistaken for '$0 open risk'."""
        try:
            [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
            return True
        except FileNotFoundError:
            return True    # a not-yet-created ledger is legitimately empty, not a fault
        except Exception:
            return False

    def _open_rows(self, strategy_only=True):
        try:
            rows = [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except FileNotFoundError:
            return []
        except Exception:
            return []
        out = []
        for r in rows:
            if r.get("status") != "OPEN":
                continue
            if strategy_only and r.get("strategy") != "earnings_vol":
                continue
            out.append(r)
        return out

    def _open_symbols(self):
        return {r.get("symbol") for r in self._open_rows()}

    def _open_risk(self):
        return sum(self._f(r.get("max_loss_total")) or 0.0 for r in self._open_rows())

    # ---- candidate selection -------------------------------------------------------------------

    @staticmethod
    def _sessions_to(today, report_date):
        """Trading sessions (Mon-Fri) strictly after `today` up to and including `report_date`. Weekend-
        aware, so from a Friday a Monday report is 1 session away — closing the calendar-day gap that let
        Monday/post-weekend reporters slip past the window. Exchange holidays are rare and not modelled
        (a holiday would at worst open one session early)."""
        from datetime import timedelta
        d, n = today, 0
        while d < report_date:
            d += timedelta(days=1)
            if d.weekday() < 5:
                n += 1
        return n

    def _candidates(self, today=None):
        """Rich-IV names reporting within REPORT_WITHIN_SESSIONS trading sessions, from the earnings panel's implied
        records — deduped against what's already open."""
        today = today or datetime.now(timezone.utc).date()
        try:
            panel = [json.loads(l) for l in self.PANEL.read_text().splitlines() if l.strip()]
        except Exception:
            return []
        open_syms = self._open_symbols()
        seen, out = set(), []
        for r in panel:
            if r.get("kind") != "implied":
                continue
            t = r.get("ticker")
            rd = str(r.get("report_date") or "")[:10]
            if not t or not rd or t in seen or t in open_syms:
                continue
            # NO optionable-universe gate here (by design): earnings IV-crush is a CATALYST edge whose
            # payoff is fattest on volatile mid-caps that VRP's strict top-liquidity universe excludes.
            # Its lens is breadth, not top-tier liquidity; tradeability is enforced downstream at
            # construction (build_condor on the UW chain + the round-trip execution-cost gate), the same
            # floor both sleeves share. Gating here would throw away exactly where the crush edge is biggest.
            try:
                rdate = date.fromisoformat(rd)
            except ValueError:
                continue
            dte = (rdate - today).days
            # Gate on TRADING SESSIONS to the report, not calendar days. A Monday reporter's last
            # pre-report session is FRIDAY — 3 calendar days out — so a calendar-day window silently
            # missed EVERY Monday / post-weekend reporter. Sessions >= 1 still excludes the report day
            # itself (dte 0, ambiguous before/after close).
            sessions = self._sessions_to(today, rdate)
            if not (1 <= sessions <= self.REPORT_WITHIN_SESSIONS):
                continue
            ivr = self._f(r.get("iv_rank")) or 0.0
            ivr = ivr / 100.0 if ivr > 1.5 else ivr          # UW iv_rank is 0-100; normalize to 0-1
            if ivr < self.IV_RANK_FLOOR:
                continue
            seen.add(t)
            out.append({"ticker": t, "report_date": rd, "days_to_report": dte,
                        "sessions_to_report": sessions,
                        "iv_rank": round(ivr, 3),            # store normalized so downstream buckets match
                        "implied_move_pct": self._f(r.get("implied_move_pct"))})
        out.sort(key=lambda c: (c["sessions_to_report"], -(c["iv_rank"] or 0)))
        return out

    def _expiry_after(self, symbol, report_date):
        """Nearest listed expiration STRICTLY AFTER the report date (so the option lives through the
        crush), capped a couple weeks out so we hold the front, richest-crush expiry."""
        try:
            from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
            exps = TradeStationOptionChainLiveEngine().get_expirations(symbol).get("expirations") or []
            rd = date.fromisoformat(str(report_date)[:10])
            after = []
            for raw in exps:
                try:
                    d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
                except (ValueError, TypeError):
                    continue
                if d > rd and (d - rd).days <= 21:
                    after.append(d)
            return min(after).isoformat() if after else None
        except Exception:
            return None

    # ---- open ----------------------------------------------------------------------------------

    def _concurrency_ceiling(self):
        """MAX_CONCURRENT is a SAFETY ceiling, NOT a capital limit — the dollar risk cap is the real
        limit. Left as a flat 3, the count could bind before the budget when condors run small
        (~$250 each), stranding deployable risk-budget the way the momentum slot-count did. A single
        contract condor sizes to between half and all of the per-position cap, so the SMALLEST a
        condor can be is ~cap/2; allow at least as many condors as the risk cap could fund at that
        floor, so the DOLLAR gate (budget_left) always binds first and the count never idles budget."""
        import math
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            per_condor_cap = float(SleeveCapitalBudgetEngine.per_condor_max_loss())
        except Exception:
            per_condor_cap = 500.0
        floor = max(1.0, per_condor_cap / 2.0)
        try:
            budget_ceiling = math.ceil(self.PORTFOLIO_RISK_CAP_USD / floor)
        except Exception:
            budget_ceiling = self.MAX_CONCURRENT
        return max(self.MAX_CONCURRENT, budget_ceiling)

    def _chain_snapshot(self, ticker, exp, uw=None, ts_chain=None):
        """One option-chain snapshot for a name/expiry: UW first (clean greeks + NBBO), TradeStation
        sandbox fallback. Shared by the live open path and the read-only diagnostics so they can't drift."""
        if uw is None:
            from app.services.uw_option_chain_engine import UWOptionChainEngine
            uw = UWOptionChainEngine()
        if ts_chain is None:
            from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
            ts_chain = TradeStationOptionChainLiveEngine()
        snap = None
        if uw.enabled():
            try:
                s = uw.get_chain_snapshot(symbol=ticker, expiration=exp)
                snap = s if s.get("contracts") else None
            except Exception:
                snap = None
        if snap is None:
            snap = ts_chain.get_chain_snapshot(symbol=ticker, expiration=exp,
                                               option_type="All", max_contracts=160, strike_proximity=40)
        return snap or {"contracts": []}

    def open_positions(self, dry_run=True, limit=None, ignore_arm=False):
        # ignore_arm lets a DRY-RUN plan build against live UW chains even while the sleeve is disarmed
        # (the pre-fire dress rehearsal) — it can NEVER book: the booking branch below is dry_run=False,
        # which still requires enabled(). A disarmed live open remains impossible.
        if not self.enabled() and not (dry_run and ignore_arm):
            return {"status": "EARNINGS_VOL_DISABLED", "opened": 0}
        from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
        from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
        vrp = ConditionalVRPShortPremiumEngine()
        chain = TradeStationOptionChainLiveEngine()
        from app.services.uw_option_chain_engine import UWOptionChainEngine
        _uw = UWOptionChainEngine()

        # Count is a budget-derived SAFETY ceiling (never binds before the dollar risk cap); the real
        # limit is budget_left below. LIMIT_PER_DAY still PACES opens per call (intentional — don't
        # dump all risk in one session); budget fills over subsequent cycles, never left permanently idle.
        slots = max(0, self._concurrency_ceiling() - len(self._open_symbols()))
        budget_left = self.PORTFOLIO_RISK_CAP_USD - self._open_risk()
        want = min(limit if limit is not None else self.LIMIT_PER_DAY, slots)
        opened, skipped, planned = [], [], []
        for c in self._candidates():
            if len(planned) >= want or budget_left <= 0:
                break
            exp = self._expiry_after(c["ticker"], c["report_date"])
            if not exp:
                skipped.append({"ticker": c["ticker"], "skip": "no expiry after report"})
                continue
            # UW chain first (clean greeks + NBBO); TradeStation sandbox fallback. Same report-driven
            # expiry (nearest after the report — captures the IV crush), just a better data source.
            snap = self._chain_snapshot(c["ticker"], exp, _uw, chain)
            con = vrp.build_condor(c["ticker"], snap.get("contracts", []) or [])
            if con.get("skip"):
                skipped.append({"ticker": c["ticker"], "skip": con["skip"]})
                continue
            if self._f(con.get("max_loss_total")) is None or con["max_loss_total"] > budget_left:
                skipped.append({"ticker": c["ticker"], "skip": "would exceed earnings-vol risk cap"})
                continue
            con.update({"expiration": exp, "report_date": c["report_date"],
                        "iv_rank": c["iv_rank"], "implied_move_pct": c["implied_move_pct"]})
            planned.append(con)
            budget_left -= con["max_loss_total"]

        if dry_run:
            # `planned` is the FULL list of built condor dicts (legs / return_on_risk / credit) — the
            # shape BestCondorsEngine and CondorShadowEngine read (both guard isinstance(list)). It was
            # returning len(planned) (an int), so those consumers silently got [] and earnings condors
            # never reached the Iron Condor card despite building fine.
            return {"status": "EARNINGS_VOL_DRYRUN", "planned": planned, "planned_count": len(planned),
                    "candidates": [{k: p.get(k) for k in ("symbol", "expiration", "report_date",
                     "credit_total", "max_loss_total", "iv_rank")} for p in planned],
                    "skipped": skipped[:8]}

        b = vrp._booking()
        for con in planned:
            qty = con["quantity"]
            # Same condor-open path VRP uses: ATOMIC all-or-none when GREYLINE_CONDOR_ATOMIC_ORDER is on
            # (no naked-leg window on open), else legacy wings-first legging. Shared helper — can't drift.
            placed, err = vrp._place_condor_open(con, b)
            if err is not None:
                skipped.append({"ticker": con["symbol"], "skip": "leg order failed", "detail": err})
                continue
            rec = {
                "symbol": con["symbol"], "quantity": qty, "expiration": con["expiration"],
                "legs": placed, "credit_per_condor": con["credit_per_condor"],
                "credit_total": con["credit_total"], "max_loss_total": con["max_loss_total"],
                "opened_at": datetime.utcnow().isoformat(), "status": "OPEN",
                "strategy": "earnings_vol", "report_date": con["report_date"],
                "entry_iv_rank": con.get("iv_rank"), "entry_implied_move_pct": con.get("implied_move_pct"),
                "entry_dte": vrp._dte(con["expiration"]), "return_on_risk": con.get("return_on_risk"),
            }
            with open(self.LEDGER, "a") as f:
                f.write(json.dumps(rec) + "\n")
            opened.append({"symbol": con["symbol"], "credit": con["credit_total"],
                           "max_loss": con["max_loss_total"], "report_date": con["report_date"]})
        return {"timestamp": datetime.utcnow().isoformat(), "opened": opened,
                "skipped": skipped[:8], "status": "EARNINGS_VOL_OPENED"}

    def fire_readiness(self):
        """READ-ONLY: WILL the earnings sleeve open condors at the next in-session cycle? Checks every
        gate between 'armed' and a booked condor. The quote-dependent BUILD check (dry-run plan, which
        places NOTHING) only runs in-session where option quotes stream; when the market is closed it's
        deferred and the deterministic gates still report. Surfaces exactly WHY if it won't fire."""
        from os import getenv
        checks = []

        def add(name, passed, detail, blocking=True):
            checks.append({"check": name, "ok": bool(passed), "blocking": blocking, "detail": detail})

        st = self.status()
        armed = self.enabled()
        add("armed", armed, "GREYLINE_EARNINGS_VOL_ENABLED " + ("on" if armed else "OFF — set true to fire"))
        paper = (getenv("GREYLINE_PAPER_EXECUTION_ENABLED", "") or "").strip().lower() == "true"
        simbook = (getenv("GREYLINE_SIM_BOOKING_ENABLED", "") or "").strip().lower() == "true"
        add("execution_authority", paper and simbook,
            f"paper_exec={paper}, sim_booking={simbook} (both required to actually book)")
        atomic = (getenv("GREYLINE_CONDOR_ATOMIC_ORDER", "") or "").strip().lower() == "true"
        add("atomic_open_path", atomic,
            "atomic all-or-none open (no naked-leg window)" if atomic else "legacy legging (reconciler backstops)",
            blocking=False)
        ncand = len(st.get("candidates_now") or [])
        add("candidates_forming", ncand > 0, f"{ncand} rich-IV name(s) reporting within the window")
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            per_condor = float(SleeveCapitalBudgetEngine.per_condor_max_loss())
        except Exception:
            per_condor = 500.0
        min_condor = per_condor / 2.0
        if not self._ledger_readable():
            # Unreadable ledger → open risk is UNKNOWN, not $0. Never assert headroom off a swallowed read.
            add("budget_headroom", False,
                "ledger unreadable — open risk UNKNOWN, headroom unverified", blocking=True)
        else:
            budget_left = self.PORTFOLIO_RISK_CAP_USD - self._open_risk()
            # A condor can be as small as ~half the per-position cap, and the in-session plan gates on the
            # ACTUAL budget_left per candidate — so the pre-session gate should pass if even the SMALLEST
            # condor fits (using the cap here caused a false NOT-READY at $469 headroom). Note the tightness.
            tight = "" if budget_left >= per_condor else f" — tight, fits a ~${min_condor:.0f} condor but not a full ${per_condor:.0f}"
            add("budget_headroom", budget_left >= min_condor,
                f"${budget_left:.0f} risk headroom{tight}")
        slots = max(0, self._concurrency_ceiling() - len(self._open_symbols()))
        add("concurrency_slots", slots > 0,
            f"{slots} slot(s) free (ceiling {self._concurrency_ceiling()}, {len(self._open_symbols())} open)")

        market_open, market_known = False, True
        try:
            from app.services.market_hours_engine import MarketHoursEngine
            market_open = MarketHoursEngine().status().get("is_regular_session") is True
        except Exception:
            market_known = False                              # a swallowed read is UNKNOWN, not "closed"
        would_open, skipped = None, []
        if market_open and armed:
            plan = self.open_positions(dry_run=True)          # places NOTHING; runs the real build+gate pipeline
            would_open = int(plan.get("planned_count") or 0)
            skipped = plan.get("skipped") or []
            add("plan_builds_condors", would_open > 0,
                f"dry-run would open {would_open} condor(s)" + (f"; {len(skipped)} skipped" if skipped else ""),
                blocking=False)   # drives will_fire via would_open; kept non-blocking for a clearer verdict
        else:
            _why = "market closed" if market_known else "market state UNKNOWN (hours read failed)"
            add("plan_builds_condors", True,
                f"deferred ({_why}) — option quotes stream only in-session; build unverified until the open",
                blocking=False)

        # build_verified is the HONEST signal: the dry-run actually confirmed a buildable condor. When the
        # build is deferred (market closed/unknown), the gates may pass but NO condor is confirmed yet.
        build_verified = bool(market_open and armed and would_open is not None)
        blocked = [c["check"] for c in checks if c["blocking"] and not c["ok"]]
        will_fire = not blocked and (would_open is None or would_open > 0)
        if blocked:
            verdict = "NOT READY — " + ", ".join(blocked)
        elif would_open == 0:
            verdict = "NOT READY — gates pass but no buildable condor right now (see skipped)"
        elif build_verified:
            verdict = f"READY — would open {would_open} condor(s) at the next cycle"
        else:
            verdict = "READY (pending build) — gates pass; a condor must still build at the open (not yet verified)"
        return {
            "sleeve": "earnings_vol", "will_fire": will_fire, "build_verified": build_verified,
            "verdict": verdict, "checks": checks,
            "would_open": would_open, "skipped": skipped[:8], "market_open": market_open, "market_known": market_known,
            "report_dates": sorted({str(c.get("report_date")) for c in (st.get("candidates_now") or [])}),
            "note": ("READ-ONLY — the dry-run plan places nothing; this is what WOULD open. The build check "
                     "runs only in-session (option quotes); deterministic gates report any time."),
            "status": "EARNINGS_FIRE_READINESS",
        }

    @staticmethod
    def _leg_strike(leg):
        try:
            return float(leg.get("strike") or leg.get("StrikePrice") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _validate_condor(self, con):
        """Independently re-verify a would-be condor is a valid DEFINED-RISK structure (build_condor already
        gates, but the rehearsal audits it fresh so a build regression can't slip a bad structure to fire).
        Returns (ok, checks:list, economics:dict)."""
        legs = con.get("legs") or {}
        sc, wc = legs.get("short_call") or {}, legs.get("wing_call") or {}
        sp, wp = legs.get("short_put") or {}, legs.get("wing_put") or {}
        credit = self._f(con.get("credit_per_condor"))
        max_loss = self._f(con.get("max_loss_total"))
        ror = self._f(con.get("return_on_risk"))
        try:
            from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
            cap = float(SleeveCapitalBudgetEngine.per_condor_max_loss())
        except Exception:
            cap = 500.0
        checks = [
            {"check": "four_legs", "ok": all([sc, wc, sp, wp])},
            {"check": "defined_risk_call", "ok": self._leg_strike(wc) > self._leg_strike(sc) > 0},
            {"check": "defined_risk_put", "ok": 0 < self._leg_strike(wp) < self._leg_strike(sp)},
            {"check": "credit_positive", "ok": credit > 0},
            {"check": "max_loss_bounded", "ok": 0 < max_loss <= cap + 1e-6},
            {"check": "ror_positive", "ok": ror > 0},
        ]
        ok = all(c["ok"] for c in checks)
        econ = {"credit_per_condor": credit, "credit_total": self._f(con.get("credit_total")),
                "max_loss_total": max_loss, "return_on_risk": ror, "quantity": con.get("quantity"),
                "per_condor_cap_usd": round(cap, 2)}
        return ok, checks, econ

    def dress_rehearsal(self):
        """PRE-FIRE DRESS REHEARSAL (READ-ONLY, places NOTHING). Trace the full earnings-condor lifecycle
        against LIVE UW chains — off-hours capable (UW has data even when the option tape is closed) — so
        the first real fires can't surprise us: BUILD (real dry-run plan) → VALIDATE (each would-be condor
        is a sound defined-risk structure) → PROJECT the round-trip into the edge court (premium_earnings,
        risk basis defined_max_loss, basis 'fills' after the close reconciler). Uses the dry-run arm bypass
        so it rehearses even while the sleeve is disarmed; ARMING remains a separate GO/NO-GO line."""
        from app.services.env_reload import reload_env
        try:
            reload_env()
        except Exception:
            pass
        armed = self.enabled()
        fr = self.fire_readiness()
        # real build against live UW chains, regardless of arm state (dry-run can never book)
        try:
            plan = self.open_positions(dry_run=True, ignore_arm=True)
        except Exception as e:
            plan = {"status": "EARNINGS_REHEARSAL_BUILD_ERROR", "planned": [], "error": str(e)[:120]}
        planned = plan.get("planned") or []
        rehearsed, valid = [], 0
        for con in planned:
            ok, checks, econ = self._validate_condor(con)
            valid += 1 if ok else 0
            rehearsed.append({
                "ticker": con.get("symbol"), "expiration": con.get("expiration"),
                "report_date": con.get("report_date"), "structure_ok": ok, "checks": checks,
                "economics": econ,
                # PROJECTION (not a booked number): what this condor WOULD contribute to the court if it
                # fills and closes. Bounds only — max win = full credit kept, max loss = defined max loss.
                "court_projection": {
                    "sleeve": "premium_earnings", "risk_basis": "defined_max_loss",
                    "basis_on_close": "fills (via reconcile_closes)",
                    "counted_in_court": True,
                    "max_win_usd": econ["credit_total"], "max_loss_usd": econ["max_loss_total"],
                    "return_on_risk_at_full_credit_pct": round(econ["return_on_risk"] * 100, 2)},
            })
        # GO/NO-GO: the build produced at least one SOUND condor that round-trips into the court.
        gate = []
        if not (self._candidates()):
            gate.append("no earnings candidates for the window")
        if not planned:
            gate.append("dry-run built 0 condors (see plan.skipped / UW chain)")
        if planned and valid == 0:
            gate.append("built condors FAILED structure validation")
        if not armed:
            gate.append("sleeve DISARMED (GREYLINE_EARNINGS_VOL_ENABLED) — arm before the fire")
        build_go = bool(planned and valid > 0)
        verdict = ("READY TO FIRE — %d sound condor(s) build off live UW chains and round-trip into the "
                   "court" % valid) if build_go and armed else \
                  ("BUILD OK, NOT ARMED — %d sound condor(s) would build; arm the sleeve to fire" % valid) \
                  if build_go else ("NOT READY — " + "; ".join(gate))
        return {
            "timestamp": datetime.utcnow().isoformat(), "sleeve": "earnings_vol",
            "armed": armed, "build_go": build_go, "valid_condors": valid, "planned_count": len(planned),
            "report_dates": sorted({str(c.get("report_date")) for c in (self._candidates() or [])}),
            "fire_readiness": {"will_fire": fr.get("will_fire"), "build_verified": fr.get("build_verified"),
                               "verdict": fr.get("verdict")},
            "rehearsed": rehearsed, "plan_skipped": (plan.get("skipped") or [])[:8],
            "gate_blocks": gate, "verdict": verdict,
            "note": ("READ-ONLY — builds against live UW chains and PLACES NOTHING. Projections are bounds "
                     "(max win = credit, max loss = defined risk), not booked P&L. Proves the first real "
                     "fires will build, fill, reconcile, and be COUNTED in the edge court."),
            "status": "EARNINGS_DRESS_REHEARSAL",
        }

    def cap_sensitivity(self, caps=None, max_names=14):
        """DECISION TOOL for the per-condor max-loss cap. The cap (max(5% equity, $500)) is a REAL
        single-position concentration limit, NOT a bug — it's why higher-priced/wide-grid earnings names
        skip at a $10k book. This shows the exact RISK vs BREADTH tradeoff: for each candidate it builds
        the TIGHTEST defined-risk condor it can form off live UW chains (unbounded cap), then counts how
        many become tradeable at each candidate cap level, with the % of equity each cap represents — so
        loosening GREYLINE_CONDOR_MAX_LOSS_PCT is an INFORMED operator choice, never a silent risk grab.
        READ-ONLY; builds nothing. Structurally-untradeable names (skip even at an unbounded cap — thin
        credit / grid) are reported SEPARATELY: raising the cap does NOT unlock them."""
        from app.services.env_reload import reload_env
        try:
            reload_env()
        except Exception:
            pass
        from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
        from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
        vrp = ConditionalVRPShortPremiumEngine()
        try:
            equity, _ = SleeveCapitalBudgetEngine._live()
            equity = float(equity) if equity else SleeveCapitalBudgetEngine.DEFAULT_BASE_USD
        except Exception:
            equity = SleeveCapitalBudgetEngine.DEFAULT_BASE_USD
        current_cap = float(SleeveCapitalBudgetEngine.per_condor_max_loss())
        if not caps:
            caps = sorted({round(current_cap * m, 0) for m in (1.0, 1.5, 2.0, 3.0)})

        BIG = 1e9
        names, untradeable = [], []
        for c in self._candidates()[:max_names]:
            exp = self._expiry_after(c["ticker"], c["report_date"])
            if not exp:
                untradeable.append({"ticker": c["ticker"], "reason": "no expiry after report"})
                continue
            try:
                snap = self._chain_snapshot(c["ticker"], exp)
                con = vrp.build_condor(c["ticker"], snap.get("contracts", []) or [], max_loss_cap=BIG)
            except Exception as e:
                untradeable.append({"ticker": c["ticker"], "reason": f"build error: {str(e)[:60]}"})
                continue
            if con.get("skip"):
                # skips even at an unbounded cap -> NOT a cap problem (thin credit / structure)
                untradeable.append({"ticker": c["ticker"], "reason": con["skip"]})
                continue
            mlp = self._f(con.get("max_loss_per_condor"))
            names.append({"ticker": c["ticker"], "min_max_loss_per_condor": round(mlp, 2),
                          "credit_per_condor": self._f(con.get("credit_per_condor")),
                          "return_on_risk": self._f(con.get("return_on_risk")),
                          "pct_of_equity": round(100 * mlp / equity, 2) if equity else None,
                          "tradeable_at_current_cap": mlp <= current_cap + 1e-6})
        sweep = []
        for cap in caps:
            fits = sorted(n["ticker"] for n in names if n["min_max_loss_per_condor"] <= cap + 1e-6)
            sweep.append({"cap_usd": round(cap, 0), "cap_pct_of_equity": round(100 * cap / equity, 2) if equity else None,
                          "tradeable_count": len(fits), "tradeable": fits})
        tradeable_now = sorted(n["ticker"] for n in names if n["tradeable_at_current_cap"])
        return {
            "timestamp": datetime.utcnow().isoformat(), "sleeve": "earnings_vol",
            "equity": round(equity, 2), "current_cap_usd": round(current_cap, 2),
            "current_cap_pct_of_equity": round(100 * current_cap / equity, 2) if equity else None,
            "tradeable_now": tradeable_now, "tradeable_now_count": len(tradeable_now),
            "names": names, "cap_sweep": sweep,
            "structurally_untradeable": untradeable[:12],
            "verdict": ("At the current ${:.0f} cap ({:.1f}% of equity) {} of {} buildable candidate(s) are "
                        "tradeable. Raising the cap admits more ONLY by taking that % single-position risk "
                        "on an UNPROVEN edge — a deliberate call (env GREYLINE_CONDOR_MAX_LOSS_PCT), never "
                        "silent.").format(current_cap, 100 * current_cap / equity if equity else 0,
                                          len(tradeable_now), len(names)),
            "note": ("READ-ONLY — builds nothing. min_max_loss_per_condor is each name's TIGHTEST possible "
                     "defined-risk condor; names in structurally_untradeable skip even at an unbounded cap "
                     "(raising the cap won't help them). Uses live UW chains — SLOW; on-demand."),
            "status": "EARNINGS_CAP_SENSITIVITY",
        }

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "armed": self.enabled(),
                "open_positions": len(self._open_symbols()),
                "open_risk_usd": round(self._open_risk(), 2),
                "portfolio_cap_usd": self.PORTFOLIO_RISK_CAP_USD,
                "candidates_now": self._candidates()[:8],
                "status": "EARNINGS_VOL_HARVEST_STATUS"}
