"""Close the learning loop: check whether each pending limit-buy actually FILLED.

Every forecast is logged PENDING with its broker order id. This reads the broker's order
status and resolves each: FILLED (with the fill price) or UNFILLED (rejected / cancelled /
expired at close). Then it lets the learning engine refine the aggressiveness from the fresh
outcomes. Read-only against the broker; safe to run every scheduler cycle.
"""

from datetime import datetime

from app.services.options_entry_learning_engine import OptionsEntryLearningEngine


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class OptionsEntryReconcilerEngine:

    FILLED_TOKENS = ("filled",)
    DEAD_TOKENS = ("rejected", "cancel", "expired", "broken", "out", "replaced")

    def __init__(self):
        self.learning = OptionsEntryLearningEngine()

    def _void_ledger(self, option_symbol, status):
        """Best-effort: a ledger failure must not stop the rest of the reconcile."""
        if not option_symbol:
            return {"voided": 0}
        try:
            from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine
            return OptionsPaperTradeLedgerEngine().void_unfilled(
                option_symbol, reason=f"BROKER_ORDER_{status.upper()[:40]}")
        except Exception:
            return {"voided": 0}

    # An entry must be at least this old before the sweep will void it, so a just-filled
    # position whose /positions read hasn't caught up yet is never mistaken for a phantom.
    SWEEP_MIN_AGE_MINUTES = 10

    def sweep_phantoms(self):
        """Void any OPEN options entry the broker neither holds nor has a working order for.

        The resolution-time void only helps orders that are still PENDING when they die.
        Entries already resolved-unfilled (or orphaned by a restart) would stay OPEN
        forever. This sweep is the general invariant: ledger OPEN must be backed by a
        broker position or a live order — nothing else counts.

        FAILS CLOSED: if the broker read is degraded we void NOTHING, because "the broker
        doesn't show it" is indistinguishable from "we couldn't ask" — and voiding a real
        position would lose track of live risk.
        """
        from app.services.broker_account_view_engine import BrokerAccountViewEngine

        view = BrokerAccountViewEngine().snapshot()
        if not view.get("reads_ok"):
            return {"status": "SWEEP_SKIPPED_BROKER_READ_DEGRADED", "voided": 0,
                    "broker_status": view.get("status")}

        held = {str(p.get("symbol") or "").upper() for p in (view.get("positions") or [])}
        working = {str(b.get("symbol") or "").upper() for b in (view.get("pending_buys") or [])}

        from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine
        led = OptionsPaperTradeLedgerEngine()
        voided, skipped_young = [], []
        for t in self._open_option_entries(led):
            sym = str(t.get("option_symbol") or "").upper()
            if not sym or sym in held or sym in working:
                continue
            if self._age_minutes(t.get("timestamp")) < self.SWEEP_MIN_AGE_MINUTES:
                skipped_young.append(sym)
                continue
            if led.void_unfilled(t.get("option_symbol"),
                                 reason="BROKER_NEVER_FILLED_SWEEP").get("voided"):
                voided.append(t.get("option_symbol"))

        return {"timestamp": datetime.utcnow().isoformat(), "voided": len(voided),
                "option_symbols": voided, "skipped_too_recent": skipped_young,
                "status": "PHANTOM_SWEEP_COMPLETE"}

    @staticmethod
    def _open_option_entries(led):
        import json
        try:
            lines = led.ledger_file.read_text().splitlines()
        except Exception:
            return []
        out = []
        for line in lines:
            if not line.strip():
                continue
            try:
                t = json.loads(line)
            except ValueError:
                continue
            if t.get("status") == "OPEN":
                out.append(t)
        return out

    @staticmethod
    def _age_minutes(ts):
        try:
            return (datetime.utcnow() - datetime.fromisoformat(str(ts))).total_seconds() / 60.0
        except Exception:
            return 1e9   # unparseable timestamp -> treat as old, not as a shield

    def _fill_price(self, order, fallback):
        legs = order.get("Legs") or [{}]
        leg = legs[0] if legs else {}
        for v in (order.get("FilledPrice"), leg.get("ExecutionPrice"),
                  leg.get("AvgFillPrice"), order.get("AverageFilledPrice")):
            p = _f(v)
            if p > 0:
                return p
        return fallback   # limit price — a buy limit fills at or better than the limit

    def reconcile(self, refine=True):
        pending = [r for r in self.learning._read_outcomes()
                   if r.get("status") == "PENDING" and r.get("order_id")]
        if not pending:
            out = {"timestamp": datetime.utcnow().isoformat(), "pending": 0, "resolved": 0,
                   "filled": 0, "unfilled": 0, "status": "NO_PENDING_ENTRY_ORDERS"}
            if refine:
                out["refine"] = self.learning.refine()
            return out

        try:
            from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine
            raw = (TradeStationOrdersLiveEngine().get_orders().get("response_json") or {}).get("Orders") or []
        except Exception as e:
            return {"timestamp": datetime.utcnow().isoformat(), "pending": len(pending),
                    "resolved": 0, "error": str(e)[:120], "status": "ORDERS_READ_FAILED"}

        by_id = {str(o.get("OrderID")): o for o in raw}
        filled = unfilled = voided = 0
        for r in pending:
            o = by_id.get(str(r.get("order_id")))
            if not o:
                continue   # not visible yet — leave PENDING for next cycle
            status = str(o.get("StatusDescription") or o.get("Status") or "").lower()
            if any(tok in status for tok in self.FILLED_TOKENS):
                self.learning.resolve(r["order_id"], True, self._fill_price(o, r.get("limit_price")))
                filled += 1
            elif any(tok in status for tok in self.DEAD_TOKENS):
                self.learning.resolve(r["order_id"], False)
                unfilled += 1
                # The order died, so no position was ever created. The ledger entry was
                # written OPEN at submit time — if we leave it, GreyLine "holds" a contract
                # the broker never gave it. Void it here; this is the self-healing path for
                # the phantom the Reality Guard caught (rejected limit orders).
                v = self._void_ledger(r.get("option_symbol"), status)
                voided += int(v.get("voided") or 0)
            # else still working (received/open/queued) — leave PENDING

        out = {"timestamp": datetime.utcnow().isoformat(), "pending": len(pending),
               "resolved": filled + unfilled, "filled": filled, "unfilled": unfilled,
               "ledger_entries_voided": voided,
               "status": "OPTIONS_ENTRY_RECONCILE_COMPLETE"}
        if refine:
            out["refine"] = self.learning.refine()
        return out
