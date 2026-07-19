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

    def _mirror_exits_to_sim(self, trade, actions):
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
            return
        symbol = trade.get("symbol")
        position_long = trade.get("side") == "BUY"
        state = trade.setdefault("doctrine_state", {})
        if "sim_shares_original" not in state:
            qty, _ = sim.sim_position(symbol)
            if qty <= 0:
                return   # no SIM counterpart (sub-share entry, or opened before booking was on)
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
            else:  # CLOSE — flatten the remaining SIM position exactly
                res = sim.close_position(symbol, position_long, reason=a["reason"],
                                         already_booked=booked_in_pass)
            events.append({"at": datetime.utcnow().isoformat(), "reason": a["reason"],
                           "type": a["type"], "result": res.get("status"),
                           "shares": res.get("shares"), "order_id": res.get("order_id")})

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
            realized = sum(a["realized"] for a in actions)
            t["realized_pnl"] = round(float(t.get("realized_pnl") or 0) + realized, 2)
            t["doctrine_state"] = state
            t["quantity"] = state["remaining_quantity"]
            t.setdefault("exit_events", []).extend(
                {**a, "at": now.isoformat()} for a in actions)
            # Mirror the same exit actions into the SIM account (best-effort, gated).
            try:
                self._mirror_exits_to_sim(t, actions)
            except Exception:
                pass
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
