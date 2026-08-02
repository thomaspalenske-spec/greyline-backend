"""Manage open option positions with the VALIDATED exit doctrine, driven by the UNDERLYING.

Replaces the old crude rule (arbitrary +50% / -35% of PREMIUM, single full close). Two
reasons that rule was wrong: (1) a premium-% stop fires on THETA — time decay alone can hit
-35% with no adverse move; (2) a single +50% full close caps the convex upside that is the
whole point of buying options.

This runs the war-gamed TradeDoctrineEngine (2.5-ATR stop; targets at 1.5/3/4.5 ATR; last
tranche runs on a 3-ATR trailing stop) on the UNDERLYING's price, via OptionsDynamicTPSEngine
which allocates the contracts across those exits and, below 4 contracts, keeps the doctrine's
risk profile through the ratcheting stop (the runner always survives). Every exit is a real
SELLTOCLOSE at the broker (full or partial), capped at the live position so it can never
oversell. And no option is ever allowed to reach maturity — it is liquidated 1 BUSINESS DAY
before expiry.

The signal that OPENS the position is a separate question (and an unproven one — flow edge is
null); this doctrine is signal-agnostic and manages whatever was opened.
"""

import json
from datetime import datetime, timedelta, time, timezone
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.market_hours_engine import MarketHoursEngine
from app.services.options_dynamic_tps_engine import OptionsDynamicTPSEngine
from app.services.momentum_exit_manager_engine import atr_for


class OptionsPositionManagerEngine:

    MAX_QUOTE_AGE_SECONDS = 900

    def __init__(self):
        self.ledger_file = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")
        self.tps = OptionsDynamicTPSEngine()

    # ---- expiry / maturity --------------------------------------------------
    def _parse_expiration(self, expiration_value):
        if not expiration_value:
            return None
        raw = str(expiration_value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=None)
        except Exception:
            return None

    @staticmethod
    def _prev_business_day(d):
        """The business day immediately before date `d` (skips Sat/Sun)."""
        d = d - timedelta(days=1)
        while d.weekday() >= 5:   # Mon=0 .. Sat=5, Sun=6
            d -= timedelta(days=1)
        return d

    def _maturity_liquidation_required(self, expiration_dt, now):
        """True once we're at/after 1 BUSINESS DAY before expiry — never hold to maturity."""
        if expiration_dt is None:
            return {"required": False, "reason": "EXPIRATION_UNAVAILABLE", "deadline": None}
        deadline = self._prev_business_day(expiration_dt.date())
        required = now.date() >= deadline
        return {"required": required,
                "reason": "WITHIN_ONE_BUSINESS_DAY_OF_EXPIRY" if required else "MATURITY_WINDOW_NOT_REACHED",
                "deadline": deadline.isoformat(), "expiry": expiration_dt.date().isoformat()}

    # ---- live underlying quote ----------------------------------------------
    def _underlying_quote(self, symbol):
        r = TradeStationQuoteLiveEngine().get_quote(symbol)
        q = ((r.get("response_json") or {}).get("Quotes") or [{}])[0]
        try:
            px = float(q.get("Last") or q.get("Mid") or q.get("Bid") or 0)
        except (TypeError, ValueError):
            px = 0.0
        delayed = bool((q.get("MarketFlags") or {}).get("IsDelayed"))
        tt = q.get("TradeTime")
        age = None
        if tt:
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(str(tt).replace("Z", "+00:00"))).total_seconds()
            except Exception:
                age = None
        return px, age, delayed

    def _sim(self):
        from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
        return GreyLineSimExecutionEngine()

    def _book_close(self, option_symbol, contracts, reason):
        """Real SELLTOCLOSE of `contracts` (partial or full). Returns (ok, booked, result)."""
        try:
            r = self._sim().book_option_close(option_symbol, contracts, reason=reason)
        except Exception as e:
            return False, 0, {"status": "SIM_CLOSE_ERROR", "error": str(e)[:120]}
        ok = (r.get("status") == "SIM_OPTION_CLOSE_BOOKED" and r.get("ok")) or \
             r.get("status") == "NO_SIM_OPTION_POSITION"
        return ok, int(r.get("contracts") or 0), r

    def manage_open_positions(self):
        if not self.ledger_file.exists():
            return {"timestamp": datetime.utcnow().isoformat(), "positions_checked": 0,
                    "positions_closed": 0, "status": "NO_OPTIONS_PAPER_LEDGER"}

        trades = [json.loads(l) for l in self.ledger_file.read_text().splitlines() if l.strip()]
        now = datetime.utcnow()
        market = MarketHoursEngine().status()
        market_open = bool(market.get("is_regular_session"))

        updated, checked, closed, scaled, blocked = [], 0, 0, 0, 0

        # BATCH-warm the shared quote cache for every open position's UNDERLYING in ONE request, so the
        # per-position _underlying_quote below hits cache instead of a serial throttle-bound TS round-trip.
        try:
            TradeStationQuoteLiveEngine().get_quotes(
                [t.get("underlying") for t in trades if t.get("status") == "OPEN" and t.get("underlying")])
        except Exception:
            pass

        for trade in trades:
            if trade.get("status") != "OPEN":
                updated.append(trade)
                continue
            checked += 1
            option_symbol = trade.get("option_symbol")
            underlying = trade.get("underlying")
            u_entry = float(trade.get("underlying_entry_price") or 0)
            contracts_now = int(trade.get("contracts") or 0)
            direction = "LONG" if str(trade.get("option_type", "")).lower().startswith("c") else "SHORT"
            atr = atr_for(underlying)

            # Doctrine needs a real underlying entry + ATR; without them we cannot manage on
            # the underlying's move. Flag rather than silently fall back to a premium rule.
            if not atr or u_entry <= 0 or contracts_now <= 0:
                trade["manager_status"] = "OPTION_DOCTRINE_UNAVAILABLE_NO_ATR_OR_ENTRY"
                updated.append(trade)
                continue

            # Attach the underlying-driven doctrine once.
            if not trade.get("exit_doctrine_underlying"):
                trade["exit_doctrine_underlying"] = self.tps.plan(u_entry, direction, atr, contracts_now)
                trade["doctrine_state_u"] = {"targets_filled": 0, "extreme": u_entry,
                                             "remaining_contracts": contracts_now}
            plan = trade["exit_doctrine_underlying"]
            state = trade["doctrine_state_u"]

            expiration_dt = self._parse_expiration(trade.get("expiration") or trade.get("contract_expiration_date"))
            maturity = self._maturity_liquidation_required(expiration_dt, now)
            trade["maturity_rule"] = maturity

            if not market_open:
                trade["manager_status"] = "OPTION_MARKET_CLOSED"
                updated.append(trade)
                continue

            upx, age, delayed = self._underlying_quote(underlying)
            if upx <= 0 or delayed or age is None or age > self.MAX_QUOTE_AGE_SECONDS:
                trade["manager_status"] = "OPTION_UNDERLYING_STALE_QUOTE_BLOCKED"
                trade["last_underlying_quote_age_seconds"] = age
                blocked += 1
                updated.append(trade)
                continue

            trade["underlying_current_price"] = round(upx, 4)
            remaining = int(state.get("remaining_contracts") or 0)

            # 1) Maturity liquidation ALWAYS wins — never hold into expiry.
            if maturity.get("required"):
                ok, booked, res = self._book_close(option_symbol, remaining, "OPTIONS_MATURITY_1_BUSINESS_DAY")
                trade.setdefault("exit_events", []).append(
                    {"at": now.isoformat(), "reason": "MATURITY_1BD", "contracts": booked,
                     "sim": res.get("status"), "order_id": res.get("order_id")})
                if ok:
                    trade["status"] = "CLOSED"; trade["exit_reason"] = "OPTIONS_MATURITY_1_BUSINESS_DAY"
                    trade["exit_timestamp"] = now.isoformat(); closed += 1
                else:
                    trade["manager_status"] = "OPTION_MATURITY_CLOSE_FAILED"
                updated.append(trade)
                continue

            # 2) Doctrine decision on the UNDERLYING's move.
            sign = 1 if direction == "LONG" else -1
            state["extreme"] = max(state["extreme"], upx) if sign > 0 else min(state["extreme"], upx)
            decision = self.tps.decide(plan, upx, int(state.get("targets_filled") or 0), state["extreme"])
            state["targets_filled"] = decision["targets_reached"]
            trade["current_stop_underlying"] = decision["stop"]
            trade["doctrine_stop_basis"] = decision["stop_basis"]
            trade["manager_status"] = f"OPTION_DOCTRINE_{decision['action']}"

            if decision["action"] == "CLOSE":     # stop hit → flatten the remainder
                ok, booked, res = self._book_close(option_symbol, remaining, "OPTIONS_DOCTRINE_STOP")
                trade.setdefault("exit_events", []).append(
                    {"at": now.isoformat(), "reason": "STOP", "contracts": booked,
                     "sim": res.get("status"), "order_id": res.get("order_id")})
                if ok:
                    trade["status"] = "CLOSED"; trade["exit_reason"] = "OPTIONS_DOCTRINE_STOP"
                    trade["exit_timestamp"] = now.isoformat(); closed += 1
                else:
                    trade["manager_status"] = "OPTION_STOP_CLOSE_FAILED"

            elif decision["action"] == "SCALE":   # a target was reached with contracts to bank
                want = min(int(decision["sell_contracts"]), remaining)
                ok, booked, res = self._book_close(option_symbol, want, f"OPTIONS_TP{decision['targets_reached']}")
                trade.setdefault("exit_events", []).append(
                    {"at": now.isoformat(), "reason": f"TP{decision['targets_reached']}",
                     "contracts": booked, "sim": res.get("status"), "order_id": res.get("order_id")})
                if ok and booked > 0:
                    remaining -= booked
                    state["remaining_contracts"] = remaining
                    trade["contracts"] = remaining     # keep ledger == broker
                    scaled += 1
                    if remaining <= 0:
                        trade["status"] = "CLOSED"; trade["exit_reason"] = "OPTIONS_LADDER_FULLY_BANKED"
                        trade["exit_timestamp"] = now.isoformat(); closed += 1

            trade["last_managed_at"] = now.isoformat()
            updated.append(trade)

        self.ledger_file.write_text("\n".join(json.dumps(t) for t in updated) + ("\n" if updated else ""))

        return {
            "timestamp": now.isoformat(), "system": "GreyLine",
            "source": "OPTIONS_POSITION_MANAGER",
            "doctrine": "underlying-ATR 2.5 stop; TP1/2/3 at 1.5/3/4.5 ATR (bank, dynamic <4); "
                        "TP4 runner trails 3 ATR; liquidate 1 business day before expiry",
            "positions_checked": checked, "positions_closed": closed,
            "positions_scaled": scaled, "stale_quote_blocked_count": blocked,
            "market_open": market_open, "market_state": market.get("state"),
            "status": "OPTIONS_POSITION_MANAGER_COMPLETE",
        }

    # ---- close-side reconciliation (the long-option mirror of VRP/momentum reconcile_closes) ----
    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    _FORCED_MARKERS = ("clean_slate", "flatten", "rebaseline", "reset", "mechanics test", "manual")

    @classmethod
    def _is_forced_close(cls, *reasons):
        for reason in reasons:
            r = str(reason or "").lower()
            if any(m in r for m in cls._FORCED_MARKERS):
                return True
        return False

    def _sim_option_positions_map(self):
        """(option_symbol -> abs contracts, readable_bool) of live SIM option positions. A swallowed read
        returns readable=False so a positions-API blip is UNKNOWN, never mistaken for a genuine flat — the
        exact conflation that let `book_option_close` report NO_SIM_OPTION_POSITION as a successful close."""
        try:
            rows = (self._sim().booking.positions().get("response_json") or {}).get("Positions") or []
        except Exception:
            return {}, False
        out = {}
        for p in rows:
            if str(p.get("AssetType") or "").upper() not in ("STOCKOPTION", "OPTION", ""):
                continue
            sym = str(p.get("Symbol") or "").upper()
            if sym:
                out[sym] = out.get(sym, 0.0) + abs(self._f(p.get("Quantity")))
        return out, True

    def _order_fills(self):
        """{order_id: (fill_price, fill_contracts, filled_bool)} from the SIM broker's order history."""
        out = {}
        try:
            orders = (self._sim().booking.orders().get("response_json") or {}).get("Orders") or []
        except Exception:
            return out
        for o in orders:
            oid = str(o.get("OrderID") or "")
            if not oid:
                continue
            filled = str(o.get("StatusDescription") or "") in ("Filled", "FLL")
            leg = (o.get("Legs") or [{}])[0]
            fp = self._f(o.get("FilledPrice")) or self._f(leg.get("ExecutionPrice"))
            fq = self._f(leg.get("ExecQuantity")) or self._f(o.get("Quantity"))
            out[oid] = (fp, fq, filled)
        return out

    def _alert_close_mismatch(self, reverted, flagged):
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return
            rv = sorted(str(x.get("option_symbol")) for x in reverted)
            fl = sorted(str(x.get("option_symbol")) for x in flagged)
            syms = sorted(set(rv) | set(fl))
            eng.dispatch(
                title="GreyLine options close mismatch — broker still holds",
                message=(f"CLOSED option row(s) the broker still holds: reverted-to-OPEN {rv or '—'}; "
                         f"partial (manual re-account) {fl or '—'}. A close reported flat but the contract "
                         "is still held (likely NO_SIM_OPTION_POSITION on a degraded read) — verify."),
                severity="CRITICAL", fingerprint=f"OPT_CLOSE_MISMATCH:{syms}")
        except Exception:
            pass

    def reconcile_closes(self, dry_run=False):
        """Close-side reconciler for LONG-OPTION exits — the mirror of VRP/momentum reconcile_closes and
        the last of the class. The options manager marks a row CLOSED whenever `_book_close` reports ok,
        which INCLUDES `NO_SIM_OPTION_POSITION` — a status a transient positions-API failure ALSO returns
        (sim_position swallows the error → (0, None) → 'no position'). So a degraded read can mark a live
        option CLOSED, and the manager books NO realized_pnl at all. Each cycle this resolves every CLOSED
        option row against ACTUAL broker state:

          * realized_pnl COMPUTED from the actual SELLTOCLOSE fills (Σ close proceeds − entry cost, ×100)
            when every exit order is Filled and the fills account for the whole original position → basis
            'fills' + stamps original_quantity so the edge court can finally see the trade. Otherwise basis
            'unreconciled' and realized_pnl is LEFT UNSET (the court keeps skipping it — never a fabricated
            number from an unconfirmed close).
          * contract STILL FULLY HELD at the broker → the 'close' was a degraded-read phantom; REVERT to
            OPEN (restore contracts + doctrine) so the manager re-attempts. CRITICAL page.
          * PARTIALLY held → ambiguous → flag CRITICAL, leave for the operator.

        Held-state logic runs ONLY on a readable positions read, never a forced/admin close, and never when
        a live re-entry explains the held contracts. Places no orders; best-effort; never raises."""
        if not self.ledger_file.exists():
            return {"status": "NO_OPTIONS_PAPER_LEDGER", "reconciled": 0, "reverted": 0, "flagged": 0}
        try:
            trades = [json.loads(l) for l in self.ledger_file.read_text().splitlines() if l.strip()]
        except Exception:
            return {"status": "OPTIONS_CLOSES_RECONCILE_DEGRADED", "reconciled": 0, "reverted": 0, "flagged": 0}
        pos, positions_ok = self._sim_option_positions_map()
        fills = self._order_fills()
        open_syms = {str(t.get("option_symbol") or "").upper()
                     for t in trades if t.get("status") == "OPEN"}
        upgraded, reverted, flagged = [], [], []
        changed = False
        for t in trades:
            if t.get("status") != "CLOSED" or t.get("exit_reconciled"):
                continue
            sym = str(t.get("option_symbol") or "").upper()
            # original size: the frozen field, else reconstruct from remaining + everything booked out
            orig = self._f(t.get("original_contracts"))
            if orig <= 0:
                orig = self._f(t.get("contracts")) + sum(self._f(e.get("contracts"))
                                                         for e in (t.get("exit_events") or []))
            entry = self._f(t.get("entry_price"))
            forced = self._is_forced_close(t.get("exit_reason"))

            # (A) held-state — readable read, non-forced, no re-entry collision
            if positions_ok and not forced and sym and sym not in open_syms:
                held = pos.get(sym, 0.0)
                if orig > 0 and held >= orig - 1e-6:            # nothing sold → phantom close
                    t["status"] = "OPEN"
                    t["contracts"] = orig
                    t["doctrine_state_u"] = {"targets_filled": 0,
                                             "extreme": self._f(t.get("underlying_entry_price")),
                                             "remaining_contracts": int(orig)}
                    t["close_reverted_at"] = datetime.utcnow().isoformat()
                    t["manager_status"] = "OPTION_CLOSE_REVERTED_STILL_HELD"
                    t["manager_status_reason"] = (f"marked CLOSED but broker still holds {held:g} contract(s) "
                                                  f"(orig {orig:g}) — close never filled; reverted to OPEN")
                    for k in ("exit_reason", "exit_timestamp", "realized_pnl", "realized_pnl_basis",
                              "close_verified_flat"):
                        t.pop(k, None)
                    reverted.append({"option_symbol": sym, "held": held})
                    changed = True
                    continue
                if held > 1e-6:                                 # partial → ambiguous
                    t["close_verified_flat"] = False
                    t["manager_status"] = "OPTION_CLOSE_PARTIALLY_HELD"
                    t["manager_status_reason"] = (f"marked CLOSED but broker still holds {held:g}/{orig:g} "
                                                  "contract(s) — re-account manually")
                    flagged.append({"option_symbol": sym, "held": held, "orig": orig})
                    changed = True
                    continue

            # (B) flat (or positions unreadable) — compute realized from the ACTUAL close fills
            evs = t.get("exit_events") or []
            oids = [str(e.get("order_id")) for e in evs if e.get("order_id")]
            proceeds, acc_qty, all_filled = 0.0, 0.0, bool(oids)
            for oid in oids:
                fp, fq, filled = fills.get(oid, (0.0, 0.0, False))
                if not filled or fp <= 0 or fq <= 0:
                    all_filled = False
                    break
                proceeds += fp * fq * 100.0                     # option point × contracts × 100
                acc_qty += fq
            if all_filled and orig > 0 and abs(acc_qty - orig) <= 1e-6:
                cost = entry * orig * 100.0                      # long option: proceeds − entry cost
                t["realized_pnl"] = round(proceeds - cost, 2)
                t["realized_pnl_basis"] = "fills"
                t["original_quantity"] = orig                    # so the edge court can read the size
                if positions_ok and not forced:
                    t["close_verified_flat"] = True
                upgraded.append({"option_symbol": sym, "realized_pnl": t["realized_pnl"]})
            else:
                # can't confirm the close fills → NEVER fabricate realized; tag honestly, court keeps skipping
                if not t.get("realized_pnl_basis"):
                    t["realized_pnl_basis"] = "unreconciled"
                if positions_ok and not forced:
                    t["close_verified_flat"] = True             # broker flat; just no fill detail to price
            t["exit_reconciled"] = True
            changed = True

        if changed and not dry_run:
            self.ledger_file.write_text("\n".join(json.dumps(t) for t in trades) + ("\n" if trades else ""))
        if not dry_run and (reverted or flagged):
            self._alert_close_mismatch(reverted, flagged)
        return {"timestamp": datetime.utcnow().isoformat(),
                "reconciled": len(upgraded), "reverted": len(reverted), "flagged": len(flagged),
                "upgrades": upgraded, "reverts": reverted, "flagged_partial": flagged,
                "status": "OPTIONS_CLOSES_RECONCILED" if not dry_run else "OPTIONS_CLOSES_RECONCILE_DRYRUN"}
