import csv
import glob
import json
import os
from datetime import datetime
from pathlib import Path

from app.services.trade_doctrine_engine import TradeDoctrineEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.persistence.json_store import atomic_write_text

HIST_DIR = "app/data/historical"
ATR_N = 14


def atr_for(symbol):
    """14-day ATR from the symbol's daily OHLC (slow-moving; CSV staleness is fine)."""
    path = os.path.join(HIST_DIR, f"{str(symbol).upper()}_daily.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                rows.append((float(r["high"]), float(r["low"]), float(r["close"])))
            except (ValueError, KeyError, TypeError):
                pass
    if len(rows) < ATR_N + 1:
        return None
    trs = []
    for i in range(len(rows) - ATR_N, len(rows)):
        h, l, _ = rows[i]
        pc = rows[i - 1][2]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return round(sum(trs) / len(trs), 6)


class MomentumExitManagerEngine:
    """
    Live application of the validated H2 exit doctrine to open momentum positions,
    replacing the plain 5-day-hold. Per position, each cycle: mark to the current quote,
    ratchet the stop, bank 25% at each of three targets, then trail the final runner.

    Pure core (`decide`) is snapshot-based: it manages on the current quote each cycle
    (~14 min granularity), not intraday high/low — so live fills can differ slightly from
    the daily-bar backtest. A MAX_HOLD backstop matches the backtest's 20-day cap.
    """

    MAX_HOLD_DAYS = 20
    TRADE_INTENT = "MOMENTUM_REVERSAL"

    def __init__(self):
        self.doctrine = TradeDoctrineEngine()
        self.ledger_file = Path("app/data/paper_trading/paper_trade_ledger.jsonl")

    def _ensure_doctrine(self, trade):
        """Lazily attach the H2 exit plan to a momentum position that lacks one, so entry
        (the rebalance) stays simple and this engine owns the whole exit lifecycle.
        Returns True if the trade is now managed, False if ATR is unavailable."""
        if trade.get("exit_doctrine"):
            return True
        atr = atr_for(trade.get("symbol"))
        entry = float(trade.get("entry_price") or 0)
        if not atr or entry <= 0:
            return False
        direction = "LONG" if trade.get("side") == "BUY" else "SHORT"
        plan = self.doctrine.exit_plan(entry, direction, atr)
        if not plan:
            return False
        qty = float(trade.get("quantity") or 0)
        trade["exit_doctrine"] = plan
        trade["original_quantity"] = qty
        trade["doctrine_state"] = {
            "tps_filled": 0, "extreme": entry, "remaining_quantity": qty,
            "opened_at": trade.get("timestamp"),
        }
        return True

    # ---- pure decision core (testable in isolation) ----
    def decide(self, trade, price, now):
        """Return (actions, new_state). actions: list of {type, qty, price, reason, realized}."""
        plan = trade.get("exit_doctrine")
        state = dict(trade.get("doctrine_state") or {})
        if not plan or not state:
            return [], state
        sign = 1 if plan["direction"] == "LONG" else -1
        remaining = float(state.get("remaining_quantity") or 0)
        if remaining <= 0:
            return [], state
        entry = float(plan["entry_price"])
        tps = state.get("tps_filled", 0)
        extreme = float(state.get("extreme", entry))
        extreme = max(extreme, price) if sign > 0 else min(extreme, price)
        state["extreme"] = extreme

        def pnl(qty, px):
            return round((px - entry) * qty * sign, 2)

        actions = []
        # bank targets crossed since last cycle (a gap can cross several)
        while tps < 3:
            tp = plan["targets"][tps]
            if (price >= tp) if sign > 0 else (price <= tp):
                qty = round(float(trade["original_quantity"]) * plan["scale_out"][tps], 6)
                qty = min(qty, remaining)
                actions.append({"type": "SCALE", "qty": qty, "price": price,
                                "reason": f"TP{tps+1}", "realized": pnl(qty, price)})
                remaining = round(remaining - qty, 6)
                tps += 1
            else:
                break
        state["tps_filled"] = tps
        state["remaining_quantity"] = remaining
        if remaining <= 1e-9:
            state["remaining_quantity"] = 0
            return actions, state

        stop = self.doctrine.current_stop(plan, tps, extreme)
        state["current_stop"] = stop
        stopped = (price <= stop) if sign > 0 else (price >= stop)
        opened = state.get("opened_at")
        held = 0
        try:
            held = (now.date() - datetime.fromisoformat(opened).date()).days
        except Exception:
            pass
        if stopped or held >= self.MAX_HOLD_DAYS:
            actions.append({"type": "CLOSE", "qty": remaining, "price": price,
                            "reason": "STOP" if stopped else "MAX_HOLD",
                            "realized": pnl(remaining, price)})
            state["remaining_quantity"] = 0
        return actions, state

    def _sim_exec(self):
        if getattr(self, "_sim", None) is None:
            from app.services.greyline_sim_execution_engine import GreyLineSimExecutionEngine
            self._sim = GreyLineSimExecutionEngine()
        return self._sim

    def _mirror_exits_to_sim(self, trade, actions, state):
        """Mirror the doctrine's exit actions into the SIM account as real orders.
        No-op unless SIM booking is enabled and a SIM position exists for the symbol.
        CLOSE flattens the whole SIM position (exact); SCALE removes the same fraction of
        the ORIGINAL SIM shares the doctrine banks.

        Scale sizing is CUMULATIVE, not per-slice: each target books
        floor(sim_original * banked_fraction_so_far) minus what is already banked. Flooring
        each 25% slice independently threw away the remainder every time — on a 2-share
        position all three targets floored to 0 and nothing was ever banked, though the
        second target legitimately covers a whole share. Cumulative sizing banks it.

        What remains is a real constraint, not an artifact: a position of 1 share cannot be
        quartered, and on a $10k book many names are 1-3 shares. Those slices round to 0 and
        are reported as SKIPPED_ZERO_SHARES — never guessed, never silently dropped."""
        sim = self._sim_exec()
        if not sim.enabled() or not actions:
            return {"attempted": False, "ok": True, "reason": "SIM booking off — internal ledger only"}
        symbol = trade.get("symbol")
        position_long = trade.get("side") == "BUY"
        # sim_* bookkeeping accumulates into the SAME `state` object the caller commits, so a confirmed
        # exit advances doctrine + bookkeeping together, and an unconfirmed one persists only bookkeeping.
        if "sim_shares_original" not in state:
            qty, _ = sim.sim_position(symbol)
            if qty <= 0:
                # No SIM counterpart to confirm against (sub-share entry / opened before booking was on).
                return {"attempted": False, "ok": True, "reason": "no SIM counterpart to confirm"}
            state["sim_shares_original"] = qty
        sim_orig = float(state.get("sim_shares_original") or 0)
        original_internal = float(trade.get("original_quantity") or 0) or 1.0
        events = trade.setdefault("sim_exit_events", [])
        # Scale-outs booked in this pass are still in flight when CLOSE reads the live
        # position, so the close must net them out or it oversells into a short.
        booked_in_pass = 0
        # Cumulative across cycles: targets are hit in different passes, so the running
        # totals live in doctrine_state alongside sim_shares_original.
        banked_fraction = float(state.get("sim_internal_banked") or 0)
        banked_shares = int(state.get("sim_shares_banked") or 0)
        all_ok, fail_reason = True, None
        for a in actions:
            if a["type"] == "SCALE":
                banked_fraction += float(a["qty"])
                target = int(sim_orig * (banked_fraction / original_internal))
                shares = max(0, target - banked_shares)
                res = sim.book_exit(symbol, shares, position_long, reason=a["reason"])
                booked = int(res.get("shares") or 0)
                banked_shares += booked
                booked_in_pass += booked
                state["sim_internal_banked"] = banked_fraction
                state["sim_shares_banked"] = banked_shares
                # SKIPPED_ZERO_SHARES = nothing to bank this pass (a legitimate no-op); a real book must
                # come back SIM_EXIT_BOOKED with a broker-confirmed ok.
                ok_a = res.get("status") == "SKIPPED_ZERO_SHARES" or (
                    res.get("status") == "SIM_EXIT_BOOKED" and bool(res.get("ok")))
            else:  # CLOSE — flatten the remaining SIM position exactly
                res = sim.close_position(symbol, position_long, reason=a["reason"],
                                         already_booked=booked_in_pass)
                # Already flat (NO_SIM_POSITION) confirms the close; otherwise at least one leg must book.
                ok_a = res.get("status") == "NO_SIM_POSITION" or (
                    res.get("status") == "SIM_BOOKED" and int(res.get("placed") or 0) > 0)
            if not ok_a:
                all_ok = False
                fail_reason = f"{a['reason']} → {res.get('status')}"
            events.append({"at": datetime.utcnow().isoformat(), "reason": a["reason"],
                           "type": a["type"], "result": res.get("status"), "ok": ok_a,
                           "shares": res.get("shares"), "order_id": res.get("order_id")})
        return {"attempted": True, "ok": all_ok, "reason": fail_reason}

    @staticmethod
    def _alert_unconfirmed_exit(trade, mirror):
        """Best-effort external alert when a momentum exit did NOT confirm at the broker — the row is
        left OPEN with no realized banked, so the operator must look rather than trust a silent CLOSE."""
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if eng.has_external_channel():
                sym = trade.get("symbol")
                eng.dispatch(
                    title="GreyLine momentum exit NOT confirmed",
                    message=(f"{sym} exit did not confirm at the broker ({mirror.get('reason')}). "
                             "Ledger left OPEN, no realized P&L banked — the position may still be live. "
                             "Check now."),
                    severity="CRITICAL", fingerprint=f"MOM_EXIT_UNCONFIRMED:{sym}")
        except Exception:
            pass

    # ---- live application over the ledger ----
    def manage_open_positions(self):
        led = PaperTradeLedgerEngine()
        trades = led._read_all()
        now = datetime.utcnow()
        quote = TradeStationQuoteLiveEngine()
        managed, closed, scaled = 0, 0, 0

        def last(sym):
            r = quote.get_quote(sym)
            q = ((r.get("response_json") or {}).get("Quotes") or [{}])[0]
            try:
                return float(q.get("Last") or 0)
            except (TypeError, ValueError):
                return 0.0

        # BATCH-warm the shared quote cache for every open momentum symbol in ONE request, so the per-
        # position last() below hits cache instead of a serial, throttle-bound TS round-trip per name (the
        # shared scheduler-cycle bottleneck). get_quote reads the same class-level cache get_quotes fills.
        try:
            quote.get_quotes([t.get("symbol") for t in trades
                              if t.get("status") == "OPEN" and t.get("trade_intent") == self.TRADE_INTENT])
        except Exception:
            pass

        changed = False
        for t in trades:
            if t.get("status") != "OPEN" or t.get("trade_intent") != self.TRADE_INTENT:
                continue
            if not self._ensure_doctrine(t):
                continue
            changed = changed or bool(t.get("exit_doctrine"))
            price = last(t.get("symbol"))
            if price <= 0:
                continue
            managed += 1
            actions, state = self.decide(t, price, now)
            if not actions:
                if state != t.get("doctrine_state"):
                    t["doctrine_state"] = state
                    changed = True
                continue
            # Reflect the exit into the SIM (paper broker) FIRST — the exit is only REAL if the broker
            # confirms it. Banking realized P&L or flipping CLOSED on INTENT records fantasy P&L and can
            # leave the position live (Reality Guard EXITS_FILLED_NOT_INTENDED catches exactly this).
            try:
                mirror = self._mirror_exits_to_sim(t, actions, state)
            except Exception as e:
                mirror = {"attempted": True, "ok": False, "reason": f"mirror raised: {str(e)[:80]}"}
            if mirror.get("attempted") and not mirror.get("ok"):
                # Broker did NOT confirm — do not bank realized, do not advance the doctrine, do not
                # CLOSE. Persist ONLY the sim_* bookkeeping (what actually booked) so the retry next
                # cycle can't double-book; decide() re-issues the unconfirmed exit. Leave the row OPEN.
                ds = t.setdefault("doctrine_state", {})
                for k, v in state.items():
                    if k.startswith("sim_"):
                        ds[k] = v
                t["manager_status"] = "MOMENTUM_EXIT_UNCONFIRMED"
                t["manager_status_reason"] = mirror.get("reason") or "SIM exit not confirmed by broker"
                self._alert_unconfirmed_exit(t, mirror)
                changed = True
                continue
            # Confirmed at the broker (or no SIM counterpart to confirm against) — commit ledger state.
            realized = sum(a["realized"] for a in actions)
            t["realized_pnl"] = round(float(t.get("realized_pnl") or 0) + realized, 2)
            t["doctrine_state"] = state
            t["quantity"] = state["remaining_quantity"]
            t.setdefault("exit_events", []).extend(
                {**a, "at": now.isoformat()} for a in actions)
            t.pop("manager_status", None)
            t.pop("manager_status_reason", None)
            scaled += sum(1 for a in actions if a["type"] == "SCALE")
            if state["remaining_quantity"] <= 0:
                t["status"] = "CLOSED"
                t["exit_price"] = actions[-1]["price"]
                t["exit_timestamp"] = now.isoformat()
                t["exit_reason"] = actions[-1]["reason"]
                closed += 1
            changed = True

        if changed:
            atomic_write_text(self.ledger_file,
                              "".join(json.dumps(t) + "\n" for t in trades))
        return {"timestamp": now.isoformat(), "engine": "MomentumExitManagerEngine",
                "managed": managed, "scaled_out": scaled, "closed": closed,
                "status": "MOMENTUM_EXIT_MANAGER_COMPLETE"}

    # ---- close-side reconciliation (the equity mirror of VRP reconcile_closes) -----------------
    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    # forced/administrative closes (clean-slate flatten, manual liquidation) are intentional — a
    # reconciler must NEVER auto-revert one, or it would resurrect a deliberately-archived position.
    _FORCED_MARKERS = ("clean_slate", "flatten", "rebaseline", "reset", "mechanics test",
                       "liquidat", "manual")

    @classmethod
    def _is_forced_close(cls, *reasons):
        for reason in reasons:
            r = str(reason or "").lower()
            if any(m in r for m in cls._FORCED_MARKERS):
                return True
        return False

    def _sim_positions_map(self):
        """(symbol -> abs held qty, readable_bool) of live SIM positions. A swallowed read returns
        readable=False so a positions-API blip is treated as UNKNOWN, never mistaken for 'flat'."""
        try:
            rows = (self._sim_exec().booking.positions().get("response_json") or {}).get("Positions") or []
        except Exception:
            return {}, False
        out = {}
        for p in rows:
            sym = str(p.get("Symbol") or "").upper()
            if sym:
                out[sym] = out.get(sym, 0.0) + abs(self._f(p.get("Quantity")))
        return out, True

    def _order_fills(self):
        """{order_id: (fill_price, fill_qty, filled_bool)} from the SIM broker's order history — the
        source of truth for what an exit actually filled at (vs the decision quote)."""
        out = {}
        try:
            orders = (self._sim_exec().booking.orders().get("response_json") or {}).get("Orders") or []
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
        """A CLOSED momentum row the broker still holds is fantasy-flat — risk live while the book says
        flat. Page it so the operator looks, whether it was auto-reverted or flagged for manual re-account."""
        try:
            from app.services.external_alert_engine import ExternalAlertEngine
            eng = ExternalAlertEngine()
            if not eng.has_external_channel():
                return
            syms = sorted({str(x.get("symbol")) for x in (reverted + flagged)})
            rv = sorted(str(x.get("symbol")) for x in reverted)
            fl = sorted(str(x.get("symbol")) for x in flagged)
            eng.dispatch(
                title="GreyLine momentum close mismatch — broker still holds",
                message=(f"CLOSED momentum row(s) the broker still holds: reverted-to-OPEN {rv or '—'}; "
                         f"partial (manual re-account) {fl or '—'}. The close never fully filled — verify."),
                severity="CRITICAL", fingerprint=f"MOM_CLOSE_MISMATCH:{syms}")
        except Exception:
            pass

    def reconcile_closes(self, dry_run=False):
        """Close-side reconciler for MOMENTUM equity exits — the equity mirror of VRP reconcile_closes.
        Momentum prices its exits off the decision QUOTE (decide() marks to the live Last) and marks CLOSED
        on broker ACCEPTANCE. Each cycle this resolves every CLOSED momentum row against ACTUAL broker state:

          * realized upgraded to the ACTUAL exit fills when every exit order is Filled and the fills account
            for the whole original position → realized_pnl_basis 'fills'. Otherwise tagged 'quote_estimate'
            (number left as-is — honest label, never a fabricated fill).
          * position STILL FULLY HELD at the broker (nothing sold) → the entire close was fantasy; REVERT to
            OPEN (reset realized/quantity/doctrine) so the manager re-attempts. CRITICAL page.
          * PARTIALLY held → too ambiguous to re-account safely (would risk double-counting a real scale-out);
            flag CRITICAL and leave for the operator, never silently mutate the number.

        Held-state logic runs ONLY when positions are READABLE (a swallowed read is UNKNOWN, never 'flat')
        and the symbol isn't explained by a live re-entry (collision guard). FORCED/admin closes are never
        reverted. Places no orders; best-effort; never raises."""
        led = PaperTradeLedgerEngine()
        try:
            trades = led._read_all()
        except Exception:
            return {"status": "NO_MOMENTUM_LEDGER", "reconciled": 0, "reverted": 0, "flagged": 0}
        pos, positions_ok = self._sim_positions_map()
        fills = self._order_fills()
        open_syms = {str(t.get("symbol") or "").upper() for t in trades
                     if t.get("status") == "OPEN" and t.get("trade_intent") == self.TRADE_INTENT}
        upgraded, reverted, flagged = [], [], []
        changed = False
        for t in trades:
            if t.get("status") != "CLOSED" or t.get("trade_intent") != self.TRADE_INTENT:
                continue
            if t.get("exit_reconciled"):
                continue
            sym = str(t.get("symbol") or "").upper()
            orig = self._f(t.get("original_quantity"))
            sign = 1 if t.get("side") == "BUY" else -1
            entry = self._f(t.get("entry_price"))
            forced = self._is_forced_close(t.get("exit_reason"), t.get("close_reason"))

            # (A) held-state — only on a readable positions read, a non-forced close, no re-entry collision
            if positions_ok and not forced and sym and sym not in open_syms:
                held = pos.get(sym, 0.0)
                if orig > 0 and held >= orig - 1e-6:            # nothing sold → the whole close was fantasy
                    t["status"] = "OPEN"
                    t["quantity"] = orig
                    t["realized_pnl"] = 0.0
                    t["doctrine_state"] = {}                    # re-derive the exit plan next cycle
                    t["close_reverted_at"] = datetime.utcnow().isoformat()
                    t["manager_status"] = "MOMENTUM_CLOSE_REVERTED_STILL_HELD"
                    t["manager_status_reason"] = (f"marked CLOSED but broker still holds {held:g} shares "
                                                  f"(orig {orig:g}) — close never filled; reverted to OPEN")
                    for k in ("exit_price", "exit_timestamp", "exit_reason", "realized_pnl_basis",
                              "close_verified_flat"):
                        t.pop(k, None)
                    reverted.append({"symbol": sym, "held": held})
                    changed = True
                    continue
                if held > 1e-6:                                 # partial: some sold, some not → ambiguous
                    t["close_verified_flat"] = False
                    t["manager_status"] = "MOMENTUM_CLOSE_PARTIALLY_HELD"
                    t["manager_status_reason"] = (f"marked CLOSED but broker still holds {held:g}/{orig:g} "
                                                  "shares — re-account manually; realized left as booked")
                    flagged.append({"symbol": sym, "held": held, "orig": orig})
                    changed = True
                    continue                                    # keep surfacing; do NOT mark reconciled

            # (B) flat (or positions unreadable) — upgrade realized to the ACTUAL fills when fully readable
            evs = t.get("sim_exit_events") or []
            oids = [str(e.get("order_id")) for e in evs if e.get("order_id")]
            proceeds, acc_qty, all_filled = 0.0, 0.0, bool(oids)
            for oid in oids:
                fp, fq, filled = fills.get(oid, (0.0, 0.0, False))
                if not filled or fp <= 0 or fq <= 0:
                    all_filled = False
                    break
                proceeds += fp * fq
                acc_qty += fq
            if all_filled and orig > 0 and abs(acc_qty - orig) <= 1e-6:
                cost = entry * orig                             # long: proceeds−cost; short: cost−proceeds
                t["realized_pnl"] = round((proceeds - cost) * sign, 2)
                t["realized_pnl_basis"] = "fills"
                if positions_ok and not forced:
                    t["close_verified_flat"] = True
                upgraded.append({"symbol": sym, "realized_pnl": t["realized_pnl"]})
            else:
                if not t.get("realized_pnl_basis"):             # legacy/partial-data row: tag honestly
                    t["realized_pnl_basis"] = "quote_estimate"
                if positions_ok and not forced:
                    t["close_verified_flat"] = True             # broker flat; just no fill detail to upgrade
            t["exit_reconciled"] = True
            changed = True

        if changed and not dry_run:
            atomic_write_text(self.ledger_file,
                              "".join(json.dumps(t) + "\n" for t in trades))
        if not dry_run and (reverted or flagged):
            self._alert_close_mismatch(reverted, flagged)
        return {"timestamp": datetime.utcnow().isoformat(),
                "reconciled": len(upgraded), "reverted": len(reverted), "flagged": len(flagged),
                "upgrades": upgraded, "reverts": reverted, "flagged_partial": flagged,
                "status": "MOMENTUM_CLOSES_RECONCILED" if not dry_run else "MOMENTUM_CLOSES_RECONCILE_DRYRUN"}
