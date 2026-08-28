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
BARS = Path("app/data/historical")           # underlying daily bars (expiry-date settle price)


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
        # Mid whenever there's a real ASK; a zero BID is a valid near-worthless quote (mid = ask/2), not
        # missing data. Requiring bid > 0 here under-marked decayed legs to 0.0 — inconsistent with the
        # _current_value gate and it distorts the condor value when only one leg of a spread has a 0 bid.
        b, a = cls._f(leg.get("bid")), cls._f(leg.get("ask"))
        return (b + a) / 2 if a > 0 and b >= 0 else 0.0

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
        crossing the spread twice is only realized if you actually close, which the exit models.

        A leg with bid == 0 but a POSITIVE ask is NOT unquotable — it's a legitimately near-worthless
        option (common on near-expiry deep-OTM condor wings), and mid = ask/2 is a fine mark. Requiring a
        positive BID left near-expiry condors permanently unpriced, which also blocked mark() from ever
        profit-taking or closing them at MANAGE_DTE. Only a non-positive ASK (no real offer at all) means
        the leg has no market and the condor can't be honestly valued this cycle."""
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
            if a <= 0 or b < 0:          # no real offer (or a bad negative bid) -> genuinely unquotable
                return None
            now[n] = {"bid": b, "ask": a}
        return self._condor_value(now)

    def _intrinsic_mark_if_blown_through(self, entry):
        """Mid-life fallback for the exact case RBLX hit: the underlying has blown PAST a short strike, so an
        ITM leg goes unquotable in UW and _current_value fails closed to None — a real loser that would then
        hide as '—' until expiry (and understate any aggregate mark). When the current spot is outside the
        short strikes, value the condor at INTRINSIC now (like the 0-DTE settle, but mid-life). A spot still
        BETWEEN the shorts is a transient quote gap, not a blown-through position -> stay unpriced (None),
        never fabricate. Returns the per-share cost-to-close, or None."""
        legs = entry.get("legs") or {}
        under = next((str((legs.get(n) or {}).get("symbol")).split()[0]
                      for n in self._LEGS if (legs.get(n) or {}).get("symbol")), None)
        if not under:
            return None
        spot = self._underlying_spot(under)
        if spot is None:
            return None
        try:
            sc = float((legs.get("short_call") or {}).get("strike"))
            sp = float((legs.get("short_put") or {}).get("strike"))
        except (TypeError, ValueError):
            return None
        if spot > sc or spot < sp:                 # blown through a short strike (deep ITM on one side)
            return self._intrinsic_close_value(legs, spot)
        return None

    @staticmethod
    def _intrinsic_close_value(legs, spot):
        """Per-share liability to close an iron condor AT EXPIRY given the underlying settle price `spot`: the
        in-the-money short spread's value, capped at its wing width; 0 between the shorts (full credit kept).
        This is how a 0-DTE condor settles once UW no longer quotes the expiring options."""
        def _s(n):
            try:
                return float((legs.get(n) or {}).get("strike"))
            except (TypeError, ValueError):
                return None
        sc, wc, sp, wp = _s("short_call"), _s("wing_call"), _s("short_put"), _s("wing_put")
        val = 0.0
        if sc is not None and wc is not None and spot > sc:
            val += min(spot - sc, abs(wc - sc))     # call spread intrinsic, capped at the wing width
        if sp is not None and wp is not None and spot < sp:
            val += min(sp - spot, abs(sp - wp))     # put spread intrinsic, capped at the wing width
        return round(max(0.0, val), 3)

    def _underlying_spot(self, symbol):
        """Best-available underlying price for expiry settlement: a live quote, else the latest daily bar close."""
        try:
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            q = TradeStationQuoteLiveEngine().get_quotes([symbol]) or {}
            row = (((q.get(symbol) or {}).get("response_json") or {}).get("Quotes") or [{}])[0]
            px = self._f(row.get("Last")) or self._f(row.get("Close"))
            if px and px > 0:
                return px
        except Exception:
            pass
        try:
            import csv
            rows = list(csv.DictReader(open(f"app/data/historical/{symbol}_daily.csv")))
            c = self._f(rows[-1].get("close"))
            return c if c and c > 0 else None
        except Exception:
            return None

    def _spot_on(self, symbol, on_date):
        """Underlying close ON `on_date` (or the nearest bar on/before it) from daily bars — the FIXED expiry
        settle price. Using this (not the drifting current spot) makes a late settle correct even days after
        expiry. None if no bar at/before the date."""
        best = None
        try:
            import csv
            with open(BARS / f"{symbol}_daily.csv") as f:
                for r in csv.DictReader(f):
                    d = str(r.get("date"))[:10]
                    if d <= on_date:
                        c = self._f(r.get("close"))
                        if c and c > 0:
                            best = c              # keep advancing -> the last bar on/before on_date
                    else:
                        break
        except Exception:
            return None
        return best

    def _expiry_close_value(self, e, dte):
        """A condor AT/PAST expiry (dte<=0) that UW no longer quotes settles at INTRINSIC vs the underlying —
        otherwise it hangs OPEN forever, never realizing P&L. Settles at the EXPIRY-DATE close (fixed, correct
        even when settled late) and falls back to the current spot. Returns (close_value_per_share, spot) or
        (None, None) if not applicable / no price available yet."""
        if dte is None or dte > 0:
            return None, None
        spot = self._spot_on(e.get("symbol"), e.get("expiration")) or self._underlying_spot(e.get("symbol"))
        if spot is None:
            return None, None
        return self._intrinsic_close_value(e.get("legs") or {}, spot), spot

    def mark(self):
        """Mark open shadow condors to MID off UW; close on profit target or near expiry."""
        entries = self._entries()
        today = self._et_date()
        closed = []
        changed = False
        for e in entries:
            if e.get("status") != "OPEN":
                continue
            dte = None
            try:
                dte = (date.fromisoformat(e["expiration"]) - date.fromisoformat(today)).days
            except Exception:
                pass
            cv = self._current_value(e.get("legs") or {})
            expiry_settle = False
            if cv is None:
                # UW won't quote a 0-DTE option, so an expiring condor would otherwise hang OPEN forever (never
                # realizing P&L, never advancing the closed count). SETTLE it at intrinsic. A transiently-
                # unquotable NON-expiring condor is left to try again next cycle.
                ev, _spot = self._expiry_close_value(e, dte)
                if ev is None:
                    continue
                cv, expiry_settle = ev, True
            credit = self._f(e.get("entry_credit_mid"))
            hit_profit = credit > 0 and cv <= (1 - self.PROFIT_TAKE_FRAC) * credit   # captured >= 50%
            near_expiry = dte is not None and dte <= self.MANAGE_DTE
            if hit_profit or near_expiry or expiry_settle:
                e["status"] = "CLOSED"
                e["closed_date"] = today
                e["close_value_per"] = round(cv, 3)
                e["realized_pnl"] = round((credit - cv) * 100 * e["quantity"], 2)
                e["close_reason"] = "expiry_settle" if expiry_settle else ("profit_take" if hit_profit else "manage_dte")
                closed.append(e["id"])
                changed = True
        if changed:
            self._rewrite(entries)
        return closed

    def _settle_expired(self):
        """Settle EVERY open position already AT/PAST expiry (dte<=0) at its EXPIRY-DATE intrinsic. RESILIENCE:
        this runs on EVERY call, BEFORE the once-daily marker and the RTH gate — an expired position must never
        hang for days because a daily cycle was missed (weekend, power loss, cycle failure). Idempotent + cheap
        (no-op when nothing is expired)."""
        entries = self._entries()
        today = self._et_date()
        closed, changed = [], False
        for e in entries:
            if e.get("status") != "OPEN":
                continue
            try:
                dte = (date.fromisoformat(e["expiration"]) - date.fromisoformat(today)).days
            except Exception:
                continue
            if dte > 0:
                continue
            cv, _spot = self._expiry_close_value(e, dte)
            if cv is None:
                continue
            credit = self._f(e.get("entry_credit_mid"))
            e["status"] = "CLOSED"
            e["closed_date"] = today
            e["close_value_per"] = round(cv, 3)
            e["realized_pnl"] = round((credit - cv) * 100 * e["quantity"], 2)
            e["close_reason"] = "expiry_settle"
            closed.append(e["id"])
            changed = True
        if changed:
            self._rewrite(entries)
        return closed

    def run_if_due(self):
        """Scheduler entry: settle expired positions (always), then open new + mark. Self-gated once/day."""
        if not self.enabled():
            return {"status": "CONDOR_SHADOW_DISABLED", "ran": False}
        # RESILIENCE: settle any already-expired position FIRST, un-gated by the once-daily marker or RTH — so a
        # missed daily cycle can't leave an expired condor dangling (the 2026-08-25 stuck-4-days-past-expiry bug).
        expired = self._settle_expired()
        # THE RULE: only OPEN a shadow condor when it could actually have executed on TradeStation (the regular
        # equity/index-option session). Fail-closed defers to the next session's run.
        from app.services.shadow_tradeability_gate import equity_session_open
        if not equity_session_open():
            return {"status": "CONDOR_SHADOW_MARKET_CLOSED", "ran": False, "expired_settled": len(expired)}
        marker = STATE / "last_run.txt"
        today = self._et_date()
        try:
            if today and marker.read_text().strip() == today:
                return {"status": "CONDOR_SHADOW_NOT_DUE", "ran": False, "expired_settled": len(expired)}
        except Exception:
            pass
        opened, closed = self.open_new(), self.mark()
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            marker.write_text(today or "")
        except Exception:
            pass
        return {"status": "CONDOR_SHADOW_RAN", "ran": True, "opened": len(opened),
                "closed": len(closed), "expired_settled": len(expired)}

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
            if cv is None and dte is not None and dte <= 0:
                # expiring today and UW no longer quotes it — show the intrinsic SETTLEMENT value, flagged, rather
                # than a bare blank that reads as missing data. It settles into realized P/L on the next mark cycle.
                ev, _spot = self._expiry_close_value(e, dte)
                cv = ev if ev is not None else cv
                row["mark_state"] = "settling"
            elif cv is None:
                # mid-life NBBO gap: if the underlying has blown PAST a short strike, mark at intrinsic so a real
                # loser (RBLX: spot below the whole put spread) doesn't hide as "—". In-band gaps stay unpriced.
                iv = self._intrinsic_mark_if_blown_through(e)
                if iv is not None:
                    cv = iv
                    row["mark_state"] = "intrinsic_gap"
            if cv is not None and credit:
                row["current_value"] = round(cv, 3)
                row["pnl_dollars"] = round((credit - cv) * 100 * qty, 2)     # short premium, real multiplier×qty
                row["pnl_pct"] = round((credit - cv) / credit * 100, 2)      # % of entry credit captured
            rows.append(row)
        rows.sort(key=lambda r: (r.get("dte") if r.get("dte") is not None else 9999,
                                 -abs(r.get("pnl_dollars") or 0)))            # soonest expiry, then most material
        return rows

    MARK_HEALTH = STATE / "mark_health.json"

    def mark_health(self, *, persist: bool = True) -> dict:
        """Make silent mark failures LOUD so a position can never again hide as '—' (the RBLX class).
        Two checks over the OPEN condors, keyed on the SYMPTOM not any one cause:
          (#2) PERSISTENT-UNPRICED — a condor with no current mark (and not legitimately settling/intrinsic_gap)
               on >=2 DISTINCT recent days. A single-cycle UW hiccup is normal and stays quiet; a multi-day gap
               is a real hidden mark. Date-based, so repeated same-day calls don't inflate it.
          (#3) CONTRADICTION — a condor whose underlying is BEYOND a wing (that side is at max loss, so the
               condor MUST be a loss) yet whose mark shows a GAIN — a marking bug even when a number IS produced.
        Idempotent; persists the per-condor unpriced-date streaks. Read by the reality guard."""
        today = self._et_date()
        rows = {(r.get("symbol"), r.get("expiration")): r for r in self.open_positions()}
        try:
            st = json.loads(self.MARK_HEALTH.read_text()) if self.MARK_HEALTH.exists() else {}
        except Exception:
            st = {}

        open_ids, unpriced_today, contradictions = set(), [], []
        for e in self._entries():
            if e.get("status") != "OPEN":
                continue
            cid = e.get("id") or f"{e.get('symbol')}-{e.get('expiration')}"
            open_ids.add(cid)
            row = rows.get((e.get("symbol"), e.get("expiration"))) or {}
            rec = st.setdefault(cid, {"symbol": e.get("symbol"), "unpriced_dates": []})
            rec["symbol"] = e.get("symbol")
            if row.get("current_value") is not None:                 # priced (incl. intrinsic_gap / settling)
                rec["unpriced_dates"] = []                           # reset the streak
                legs = e.get("legs") or {}
                spot = self._underlying_spot(e.get("symbol"))
                try:
                    wc = float((legs.get("wing_call") or {}).get("strike"))
                    wp = float((legs.get("wing_put") or {}).get("strike"))
                except (TypeError, ValueError):
                    wc = wp = None
                pnl = row.get("pnl_dollars")
                if spot is not None and wc is not None and wp is not None and pnl is not None:
                    if (spot > wc or spot < wp) and pnl > 0:         # past a wing but marked a GAIN = impossible
                        contradictions.append({"symbol": e.get("symbol"), "spot": round(spot, 2),
                                               "wing_call": wc, "wing_put": wp, "pnl_dollars": pnl})
            else:                                                    # unpriced this cycle
                # Only COUNT a pricing failure during the equity session — unpriced overnight/weekends is
                # expected (no live quotes) and must not accrue a false streak. The contradiction check (#3)
                # stays ungated (a produced mark is inconsistent regardless of the clock).
                try:
                    from app.services.shadow_tradeability_gate import equity_session_open
                    rth = equity_session_open()
                except Exception:
                    rth = False
                if today and rth and today not in rec["unpriced_dates"]:
                    rec["unpriced_dates"].append(today)
                unpriced_today.append(e.get("symbol"))

        for cid in [c for c in st if c not in open_ids]:             # prune closed condors
            del st[cid]

        def _recent(dates):
            try:
                from datetime import date, timedelta
                cut = (date.fromisoformat(today) - timedelta(days=6)) if today else None
                return sorted(d for d in dates if not cut or date.fromisoformat(d) >= cut)
            except Exception:
                return dates
        persistent = [{"condor": cid, "symbol": rec.get("symbol"), "days_unpriced": len(_recent(rec.get("unpriced_dates", [])))}
                      for cid, rec in st.items() if len(_recent(rec.get("unpriced_dates", []))) >= 2]

        if persist:
            try:
                self.MARK_HEALTH.write_text(json.dumps(st, indent=1))
            except Exception:
                pass
        return {"status": "CONDOR_MARK_HEALTH", "open_condors": len(open_ids),
                "unpriced_today": unpriced_today, "persistent_unpriced": persistent,
                "contradictions": contradictions,
                "ok": not persistent and not contradictions}

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
