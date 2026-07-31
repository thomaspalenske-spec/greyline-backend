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

    def _open_rows(self, strategy_only=True):
        try:
            rows = [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
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

    def open_positions(self, dry_run=True, limit=None):
        if not self.enabled():
            return {"status": "EARNINGS_VOL_DISABLED", "opened": 0}
        from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
        from app.services.tradestation_option_chain_live_engine import TradeStationOptionChainLiveEngine
        vrp = ConditionalVRPShortPremiumEngine()
        chain = TradeStationOptionChainLiveEngine()
        from app.services.uw_option_chain_engine import UWOptionChainEngine
        _uw = UWOptionChainEngine()

        slots = max(0, self.MAX_CONCURRENT - len(self._open_symbols()))
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
            snap = None
            if _uw.enabled():
                try:
                    s = _uw.get_chain_snapshot(symbol=c["ticker"], expiration=exp)
                    snap = s if s.get("contracts") else None
                except Exception:
                    snap = None
            if snap is None:
                snap = chain.get_chain_snapshot(symbol=c["ticker"], expiration=exp,
                                                option_type="All", max_contracts=160, strike_proximity=40)
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
            order = [("wing_call", "BUYTOOPEN"), ("wing_put", "BUYTOOPEN"),
                     ("short_call", "SELLTOOPEN"), ("short_put", "SELLTOOPEN")]
            placed, leg_err = [], False
            for name, action in order:
                leg = con["legs"][name]
                px = leg["ask"] if action == "BUYTOOPEN" else leg["bid"]
                r = b.place_order(leg["symbol"], qty, action=action, order_type="Limit",
                                  limit_price=vrp._tick_round(px), tif="DAY")
                if r.get("ok"):
                    placed.append({"symbol": leg["symbol"], "action": action,
                                   "order_id": r.get("order_id"), "limit": vrp._tick_round(px)})
                else:
                    leg_err = True
                    break
            if leg_err:
                skipped.append({"ticker": con["symbol"], "skip": "leg order failed"})
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

    def status(self):
        return {"timestamp": datetime.utcnow().isoformat(), "armed": self.enabled(),
                "open_positions": len(self._open_symbols()),
                "open_risk_usd": round(self._open_risk(), 2),
                "portfolio_cap_usd": self.PORTFOLIO_RISK_CAP_USD,
                "candidates_now": self._candidates()[:8],
                "status": "EARNINGS_VOL_HARVEST_STATUS"}
