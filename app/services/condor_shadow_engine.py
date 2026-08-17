"""Condor SHADOW forward-test — measures the VRP/earnings short-premium edge on real UW quotes.

The TradeStation SIM sandbox can't price or fill condors (garbage option quotes), so the live condor
sleeves can't be trusted to forward-test the edge. This engine does it honestly: it records the condors
VRP + earnings WOULD open (built off Unusual Whales' clean greeks + NBBO), then marks them to market
each day off UW and books hypothetical P&L on the same discipline the live engine uses (take profit at
50% of the entry credit, close near expiry). NO orders — decoupled from SIM execution, same pattern as
the managed-futures shadow. When EdgePersistence has enough closed shadow condors, it's a real read on
whether the variance-risk-premium harvest actually pays after real spreads.
"""

import json
import math
from datetime import date, datetime
from os import getenv
from pathlib import Path
from app.services.ttl_cache import ttl_cached

STATE = Path("app/data/condor_shadow")
LEDGER = STATE / "shadow_ledger.jsonl"


class CondorShadowEngine:

    PROFIT_TAKE_FRAC = 0.50      # close when 50% of the entry credit has been captured
    MANAGE_DTE = 7               # close this many days before expiry regardless
    MIN_DAYS = 10                # accumulating until this many CLOSED condors (mirrors EdgePersistence)

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def enabled():
        return (getenv("GREYLINE_CONDOR_SHADOW", "true") or "true").strip().lower() == "true"

    # ---- ledger --------------------------------------------------------------------------------
    def _entries(self):
        out = []
        try:
            for ln in LEDGER.read_text().splitlines():
                if ln.strip():
                    out.append(json.loads(ln))
        except Exception:
            pass
        return out

    def _rewrite(self, entries):
        STATE.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def _append(self, entry):
        STATE.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(entry) + "\n")

    ERRORS = STATE / "sleeve_errors.json"

    def _write_sleeve_errors(self, errors):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            self.ERRORS.write_text(json.dumps(errors or {}))
        except Exception:
            pass

    def _read_sleeve_errors(self):
        try:
            return json.loads(self.ERRORS.read_text()) or {}
        except Exception:
            return {}

    # ---- what the sleeves WOULD open (built off UW) --------------------------------------------
    def _candidate_condors(self):
        """Returns (condors, errors). A sleeve that THROWS is recorded in `errors` rather than silently
        vanishing — a silently-failing sleeve corrupts the forward-test verdict with survivorship (only
        the days it happened to work get recorded). Mirrors best_condors._gather's sleeve_errors."""
        condors, errors = [], {}
        try:
            from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
            # plan_cached: reuse the sleeve's in-cycle plan (forward-test recorder, never books) instead of
            # a 3rd redundant rebuild off the same UW chains.
            for con in (ConditionalVRPShortPremiumEngine().plan_cached().get("planned") or []):
                con["_sleeve"] = "vrp"
                condors.append(con)
        except Exception as e:
            errors["vrp"] = repr(e)[:160]
        try:
            from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine
            r = EarningsVolHarvestEngine().open_positions(dry_run=True)
            for con in (r.get("planned") if isinstance(r.get("planned"), list) else []) or []:
                con["_sleeve"] = "earnings"
                condors.append(con)
        except Exception as e:
            errors["earnings"] = repr(e)[:160]
        # INDEX VRP (XSP-first): cash-settled index condors — the deepest, tightest-spread variance premium,
        # and no SIM atomic-close break. Opt-in (GREYLINE_INDEX_CONDOR_SHADOW); measured as its own sleeve.
        try:
            from app.services.index_condor_plan_engine import IndexCondorPlanEngine
            _ie = IndexCondorPlanEngine()
            if _ie.enabled():
                for con in (_ie.plan().get("planned") or []):
                    con.setdefault("_sleeve", "index_vrp")   # planner tags per factor (index_vrp / commodity_vrp)
                    condors.append(con)
        except Exception as e:
            errors["index_vrp"] = repr(e)[:160]
        return condors, errors

    _LEGS = ("short_call", "wing_call", "short_put", "wing_put")

    def _legs_entry(self, con):
        """Store each leg's symbol/strike/entry-bid/ask so the position can be MID-marked later."""
        legs = con.get("legs") or {}
        out = {}
        for n in self._LEGS:
            l = legs.get(n) or {}
            out[n] = {"symbol": l.get("symbol"), "strike": l.get("strike"),
                      "bid": self._f(l.get("bid")), "ask": self._f(l.get("ask"))}
        return out

    @classmethod
    def _mid(cls, leg):
        b, a = cls._f(leg.get("bid")), cls._f(leg.get("ask"))
        return (b + a) / 2 if (b > 0 and a > 0) else 0.0

    @classmethod
    def _condor_value(cls, legs):
        """Fair (MID) value still in the condor = shorts' mid − wings' mid (per share)."""
        return (cls._mid(legs["short_call"]) + cls._mid(legs["short_put"])) \
            - (cls._mid(legs["wing_call"]) + cls._mid(legs["wing_put"]))

    # ---- open + mark ---------------------------------------------------------------------------
    def _et_date(self):
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        except Exception:
            return None

    def open_new(self):
        """Record condors the sleeves would open now that aren't already an OPEN shadow (dedupe by
        symbol+expiry). Entry credit/legs are captured from the UW-built plan."""
        today = self._et_date()
        entries = self._entries()
        open_keys = {(e["symbol"], e["expiration"]) for e in entries if e.get("status") == "OPEN"}
        added = []
        cands, errors = self._candidate_condors()
        self._write_sleeve_errors(errors)   # persist so report() can surface a silently-failing sleeve
        for con in cands:
            key = (con.get("symbol"), con.get("expiration"))
            if not key[0] or not key[1] or key in open_keys:
                continue
            legs = self._legs_entry(con)
            entry_mid = self._condor_value(legs)
            if entry_mid <= 0:
                continue
            entry = {
                "id": f"{key[0]}-{key[1]}-{today}",
                "symbol": key[0], "expiration": key[1], "sleeve": con.get("_sleeve"),
                "opened_date": today, "opened_at": datetime.utcnow().isoformat(),
                "entry_credit_per": self._f(con.get("credit_per_condor")),   # marketable (build_condor)
                "entry_credit_mid": round(entry_mid, 3),                     # fair value at entry (mid)
                "quantity": int(con.get("quantity") or 1),
                "max_loss_per": self._f(con.get("max_loss_total")) / max(1, int(con.get("quantity") or 1)),
                "iv_rank": con.get("iv_rank"),
                "legs": legs,
                "status": "OPEN",
            }
            self._append(entry)
            open_keys.add(key)
            added.append(entry["id"])
        return added

    def _current_value(self, legs):
        """Current MID value still in the condor off UW (shorts' mid − wings' mid), per share. None if
        any leg is unquotable. Held to profit-target/expiry, so mid (fair value) is the honest mark —
        crossing the spread twice is only realized if you actually close, which the exit models."""
        from app.services.uw_option_quote_engine import UWOptionQuoteEngine
        q = UWOptionQuoteEngine()
        if not q.enabled():
            return None
        now = {}
        for n in self._LEGS:
            sym = (legs.get(n) or {}).get("symbol")
            if not sym:
                return None
            b, a = q.quote(sym)
            if b <= 0 or a <= 0:
                return None
            now[n] = {"bid": b, "ask": a}
        return self._condor_value(now)

    def mark(self):
        """Mark open shadow condors to MID off UW; close on profit target or near expiry."""
        entries = self._entries()
        today = self._et_date()
        closed = []
        changed = False
        for e in entries:
            if e.get("status") != "OPEN":
                continue
            cv = self._current_value(e.get("legs") or {})
            if cv is None:
                continue
            credit = self._f(e.get("entry_credit_mid"))
            dte = None
            try:
                dte = (date.fromisoformat(e["expiration"]) - date.fromisoformat(today)).days
            except Exception:
                pass
            hit_profit = credit > 0 and cv <= (1 - self.PROFIT_TAKE_FRAC) * credit   # captured >= 50%
            near_expiry = dte is not None and dte <= self.MANAGE_DTE
            if hit_profit or near_expiry:
                e["status"] = "CLOSED"
                e["closed_date"] = today
                e["close_value_per"] = round(cv, 3)
                e["realized_pnl"] = round((credit - cv) * 100 * e["quantity"], 2)
                e["close_reason"] = "profit_take" if hit_profit else "manage_dte"
                closed.append(e["id"])
                changed = True
        if changed:
            self._rewrite(entries)
        return closed

    def run_if_due(self):
        """Scheduler entry: open new shadow condors, then mark existing. Self-gated once/day."""
        if not self.enabled():
            return {"status": "CONDOR_SHADOW_DISABLED", "ran": False}
        # THE RULE: only open/settle a shadow condor when it could actually have executed on TradeStation
        # (the regular equity/index-option session). Fail-closed defers to the next session's run.
        from app.services.shadow_tradeability_gate import equity_session_open
        if not equity_session_open():
            return {"status": "CONDOR_SHADOW_MARKET_CLOSED", "ran": False}
        marker = STATE / "last_run.txt"
        today = self._et_date()
        try:
            if today and marker.read_text().strip() == today:
                return {"status": "CONDOR_SHADOW_NOT_DUE", "ran": False}
        except Exception:
            pass
        opened, closed = self.open_new(), self.mark()
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            marker.write_text(today or "")
        except Exception:
            pass
        return {"status": "CONDOR_SHADOW_RAN", "ran": True, "opened": len(opened), "closed": len(closed)}

    # ---- report --------------------------------------------------------------------------------
    def _slice_metrics(self, entries):
        """The forward-test numbers for a subset of condors (all, or one sleeve): closed count, realized,
        win rate, marked unrealized, and an accumulating/measuring verdict. One code path so the overall
        and per-sleeve reads can never drift."""
        closed = [e for e in entries if e.get("status") == "CLOSED"]
        open_ = [e for e in entries if e.get("status") == "OPEN"]
        realized = round(sum(self._f(e.get("realized_pnl")) for e in closed), 2)
        wins = sum(1 for e in closed if self._f(e.get("realized_pnl")) > 0)
        unrealized, marked = 0.0, 0
        for e in open_:
            cv = self._current_value(e.get("legs") or {})
            if cv is not None:
                unrealized += (self._f(e.get("entry_credit_mid")) - cv) * 100 * e["quantity"]
                marked += 1
        n = len(closed)
        accumulating = n < self.MIN_DAYS
        return {
            "open_condors": len(open_), "closed_condors": n, "min_closed": self.MIN_DAYS,
            "realized_pnl": realized, "unrealized_pnl": round(unrealized, 2), "open_marked": marked,
            "win_rate_pct": round(100 * wins / n, 1) if n else None,
            "status": ("CONDOR_SHADOW_ACCUMULATING" if accumulating else "CONDOR_SHADOW_MEASURING"),
            "verdict": (f"accumulating ({n}/{self.MIN_DAYS} closed) — not enough to trust yet" if accumulating
                        else f"measuring: {n} closed, realized ${realized}, win rate "
                             f"{round(100*wins/n,1) if n else 0}%"),
        }

    def open_positions(self):
        """Per-OPEN-condor rows for the dashboard: entry credit -> current mark -> unrealized P/L, using the
        condor's ACTUAL contract quantity × the 100 options multiplier (this is a real size, not the shadows'
        hypothetical 100-share lot). Short premium: P/L = (entry credit − current value) × 100 × qty; % is the
        share of the entry credit captured. Marked to UW mid — a condor whose legs can't be quoted this cycle
        is returned UNPRICED (current/P&L None), never fabricated."""
        today = self._et_date()
        try:
            today_d = date.fromisoformat(today) if today else None
        except (ValueError, TypeError):
            today_d = None
        rows = []
        for e in self._entries():
            if e.get("status") != "OPEN":
                continue
            credit = self._f(e.get("entry_credit_mid"))
            qty = int(e.get("quantity") or 1)
            cv = self._current_value(e.get("legs") or {})
            try:
                dte = (date.fromisoformat(e["expiration"]) - today_d).days if today_d else None
            except Exception:
                dte = None
            row = {"symbol": e.get("symbol"), "sleeve": e.get("sleeve"), "expiration": e.get("expiration"),
                   "contracts": qty, "entry_credit": round(credit, 3) if credit else None,
                   "iv_rank": e.get("iv_rank"), "dte": dte}
            if cv is not None and credit:
                row["current_value"] = round(cv, 3)
                row["pnl_dollars"] = round((credit - cv) * 100 * qty, 2)     # short premium, real multiplier×qty
                row["pnl_pct"] = round((credit - cv) / credit * 100, 2)      # % of entry credit captured
            rows.append(row)
        rows.sort(key=lambda r: (r.get("dte") if r.get("dte") is not None else 9999,
                                 -abs(r.get("pnl_dollars") or 0)))            # soonest expiry, then most material
        return rows

    @ttl_cached(30, env_key="GREYLINE_SHADOW_CACHE_TTL")
    def report(self):
        entries = self._entries()
        overall = self._slice_metrics(entries)
        # PER-SLEEVE breakout — the whole point of two independent forward-tests: measure the EARNINGS-vol
        # edge distinctly from VRP (they blended into one verdict before), mirroring the edge court's
        # premium_vrp / premium_earnings split. A sleeve with no condors yet just reports 0 closed.
        by_sleeve = {s: self._slice_metrics([e for e in entries if (e.get("sleeve") or "") == s])
                     for s in ("vrp", "earnings", "index_vrp", "commodity_vrp", "energy_vrp",
                               "rates_vrp", "crypto_vrp")}
        # A sleeve that threw during candidate-generation is surfaced (not silently dropped) so the
        # operator knows the forward-test is running on partial input and its verdict may be biased.
        sleeve_errors = self._read_sleeve_errors()
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "shadow_enabled": self.enabled(),
            **overall,
            "open_positions": self.open_positions(),   # per-condor rows for the card (entry->mark->P/L)
            "by_sleeve": by_sleeve,
            "sleeve_errors": sleeve_errors,
            "degraded": bool(sleeve_errors),
            "status": ("CONDOR_SHADOW_DEGRADED" if sleeve_errors else overall["status"]),
            "note": ("Hypothetical short-premium condors built + priced off Unusual Whales (clean greeks "
                     "+ NBBO), NO orders — the real VRP/earnings forward-test the SIM sandbox can't run. "
                     "by_sleeve measures the earnings-vol edge SEPARATELY from VRP."),
        }
