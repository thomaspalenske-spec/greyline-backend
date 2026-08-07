"""Sleeve trade ledger — makes the direct-to-broker EQUITY/ETF sleeves (trend / vol-carry /
managed-futures / low-vol) VISIBLE to the edge court.

The problem it fixes (2026-08-04): these four sleeves book straight to the SIM via place_order and
write to NONE of the ledgers EdgePersistenceEngine reads (equity/options/VRP). So their closes never
accumulate toward any sleeve's required_n — Edge D+ could never move through them no matter how long
they traded. This ledger is the missing pipe.

DESIGN — broker-confirmed, not order-confirmed. Recording is driven by OBSERVED broker position deltas
(reconcile), NOT by orders placed. An unfilled patient-limit order changes nothing; only a CONFIRMED
change in the broker-held quantity opens a lot or closes one. This is immune to the phantom / fantasy-
realized bug class (ledger claims a fill the broker never made) that bit the flatten and the condor
closes. FIFO lots; realized P&L = (exit_mark - lot_entry) * qty. The quantity is broker-truth; the
price marks are the sleeve's current quote (basis 'quote_estimate' — honest, not fill-confirmed).

Each CLOSE row carries an EXPLICIT `sleeve` tag so the court attributes it directly (never guesses via
_sleeve_of, which only knew momentum). close_reason 'REBALANCE'/'EXIT' is NON-forced, so these DO count
(unlike clean-slate flattens the court excludes).
"""

import json
from datetime import datetime
from pathlib import Path


class SleeveTradeLedgerEngine:

    LEDGER = Path("app/data/paper_trading/sleeve_trade_ledger.jsonl")

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _read(self):
        try:
            return [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def _write(self, rows):
        self.LEDGER.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.LEDGER.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
        tmp.replace(self.LEDGER)

    def _open_lots(self, rows, sleeve, symbol):
        return [r for r in rows if r.get("kind") == "lot" and r.get("sleeve") == sleeve
                and r.get("symbol") == symbol and self._f(r.get("remaining")) > 0]

    def held_qty(self, sleeve, symbol):
        return int(sum(self._f(r.get("remaining")) for r in self._open_lots(self._read(), sleeve, str(symbol).upper())))

    @staticmethod
    def _per_sleeve_armed():
        from os import getenv
        return (getenv("GREYLINE_PER_SLEEVE_SIZING", "") or "").strip().lower() == "true"

    def held_qty_excluding(self, exclude_sleeve, symbol, rows=None):
        """Confirmed open qty of `symbol` held by ALL sleeves EXCEPT exclude_sleeve. Used to attribute a
        sleeve only its SHARE of a symbol two sleeves can both trade (trend ∩ xs_momentum overlap)."""
        rows = self._read() if rows is None else rows
        sym = str(symbol).upper()
        return int(sum(self._f(r.get("remaining")) for r in rows
                       if r.get("kind") == "lot" and str(r.get("symbol")).upper() == sym
                       and r.get("sleeve") != exclude_sleeve and self._f(r.get("remaining")) > 0))

    def reconcile(self, sleeve, symbol, broker_qty, price, reason=None, now=None):
        """Reconcile the ledger's lot quantity for (sleeve, symbol) to the CONFIRMED broker quantity.
        broker_qty > ledger -> a buy filled (open a lot at `price`). broker_qty < ledger -> a sell filled
        (consume lots FIFO, emit CLOSE rows with realized P&L). Equal -> no-op. Records only what the
        broker actually holds, so an unfilled order never fabricates a fill."""
        symbol = str(symbol).upper()
        price = self._f(price)
        ts = now or datetime.utcnow().isoformat()
        rows = self._read()
        have = int(sum(self._f(r.get("remaining")) for r in self._open_lots(rows, sleeve, symbol)))
        try:
            broker_qty = int(round(float(broker_qty)))
        except (TypeError, ValueError):
            return {"status": "SLEEVE_LEDGER_BAD_QTY", "sleeve": sleeve, "symbol": symbol}
        delta = broker_qty - have
        if delta == 0 or price <= 0:
            return {"status": "SLEEVE_LEDGER_NOOP", "sleeve": sleeve, "symbol": symbol,
                    "broker_qty": broker_qty, "ledger_qty": have}

        if delta > 0:
            adopted = (have == 0 and not self._open_lots(rows, sleeve, symbol))
            rows.append({"kind": "lot", "sleeve": sleeve, "symbol": symbol, "qty": delta,
                         "remaining": delta, "entry_price": price, "opened_at": ts, "status": "OPEN",
                         "adopted": bool(adopted)})   # adopted: a pre-existing broker position, basis = mark now
            self._write(rows)
            return {"status": "SLEEVE_LEDGER_OPENED", "sleeve": sleeve, "symbol": symbol, "qty": delta}

        to_close = -delta
        closed = []
        for lot in sorted(self._open_lots(rows, sleeve, symbol), key=lambda r: str(r.get("opened_at"))):
            if to_close <= 0:
                break
            take = min(int(self._f(lot.get("remaining"))), to_close)
            if take <= 0:
                continue
            lot["remaining"] = self._f(lot.get("remaining")) - take
            if lot["remaining"] <= 0:
                lot["status"] = "CLOSED"
            entry = self._f(lot.get("entry_price"))
            realized = round((price - entry) * take, 2)
            rows.append({"kind": "close", "sleeve": sleeve, "symbol": symbol, "quantity": take,
                         "entry_price": entry, "exit_price": price, "realized_pnl": realized,
                         "opened_at": lot.get("opened_at"), "closed_at": ts,
                         "close_reason": reason or "REBALANCE", "status": "CLOSED",
                         "realized_pnl_basis": "quote_estimate"})
            closed.append({"qty": take, "realized_pnl": realized})
            to_close -= take
        self._write(rows)
        return {"status": "SLEEVE_LEDGER_CLOSED", "sleeve": sleeve, "symbol": symbol,
                "closed": closed, "unmatched": to_close,
                "realized_total": round(sum(c["realized_pnl"] for c in closed), 2)}

    @staticmethod
    def _pos_price(p):
        for k in ("Last", "MarkToMarketPrice", "MarkPrice", "AveragePrice"):
            v = p.get(k)
            if v not in (None, "", 0, "0"):
                try:
                    return abs(float(v))
                except (TypeError, ValueError):
                    continue
        return 0.0

    def reconcile_from_broker(self, sleeve, symbols):
        """RECONCILE-FIRST: sync this sleeve's confirmed held to the CURRENT broker BEFORE the sleeve sizes,
        so the ledger is never stale at decision time — the reconcile-after-sizing lag that let deltas
        explode (2026-08-06). Reads positions ONCE (shared cache); prices come from the position mark, or
        the sleeve's own last lot entry as a fallback so a sold-off name can still be priced to CLOSE.
        Delegates the share-attribution + empty-read guard to reconcile_plan."""
        try:
            from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
            rj = (TradeStationPositionsLiveEngine().get_positions().get("response_json") or {})
        except Exception as e:
            return {"status": "RECONCILE_FIRST_READ_FAILED", "sleeve": sleeve, "detail": str(e)[:100]}
        posmap = {str(p.get("Symbol")).upper(): p for p in (rj.get("Positions") or [])
                  if str(p.get("AssetType")) == "STOCK"}
        rows = self._read()
        legs = []
        for sym in symbols:
            s = str(sym).upper()
            p = posmap.get(s)
            qty = int(self._f(p.get("Quantity"))) if p else 0
            price = self._pos_price(p) if p else 0.0
            if price <= 0:                                  # sold-off name: price the close from our own lot
                lots = self._open_lots(rows, sleeve, s)
                if lots:
                    price = self._f(lots[-1].get("entry_price"))
            if price > 0:
                legs.append({"symbol": s, "broker_total": qty, "last": price})
        if not legs:
            return {"status": "RECONCILE_FIRST_NOOP", "sleeve": sleeve}
        return self.reconcile_plan(sleeve, legs)

    def reconcile_plan(self, sleeve, legs, reason=None):
        """Reconcile every basket leg from a sleeve plan in one pass. Reads each leg's broker-held qty and
        a current price mark under flexible keys so it works across the sleeves' slightly different plans."""
        legs = legs or []
        # EMPTY-READ GUARD: if EVERY basket leg reports 0 held but we DO hold open lots, the broker read
        # almost certainly came back empty/degraded — an all-positions-vanished event is implausible.
        # Skip rather than fabricate a mass close (the phantom / fantasy-realized bug class). A genuine
        # single-name sell (other names still held) is unaffected.
        # Key the guard on the WHOLE broker position (broker_total), not the sleeve's share: once per-sleeve
        # sizing is armed a sleeve's `held` is legitimately 0 for a symbol another sleeve owns — that is not
        # a degraded read. broker_total is 0 for every leg only when the positions read truly came back empty.
        held_vals = [leg.get("broker_total", leg.get("held")) for leg in legs
                     if leg.get("broker_total", leg.get("held")) is not None]
        if held_vals and all(int(self._f(h)) == 0 for h in held_vals):
            rows = self._read()
            if any(self._open_lots(rows, sleeve, str(leg.get("symbol")).upper())
                   for leg in legs if leg.get("symbol")):
                return {"status": "SLEEVE_LEDGER_SKIP_EMPTY_READ", "sleeve": sleeve}
        armed = self._per_sleeve_armed()
        rows = self._read() if armed else None
        out = []
        for leg in legs:
            sym = leg.get("symbol")
            # `broker_total` is the WHOLE broker position for the symbol; `held` may be the sleeve's own
            # share once per-sleeve sizing is armed, so prefer broker_total for the total.
            qty = leg.get("broker_total", leg.get("held", leg.get("shares", leg.get("quantity"))))
            price = leg.get("last", leg.get("price", leg.get("current", leg.get("mark"))))
            if not sym or qty is None or not price:
                continue
            target = qty
            if armed:
                # attribute this sleeve only ITS share of a symbol other sleeves may also hold: the broker
                # total minus what every OTHER sleeve confirmed-holds. Never negative (a sleeve can't owe
                # shares). For a disjoint symbol others=0 -> target == broker total (byte-identical).
                try:
                    others = self.held_qty_excluding(sleeve, sym, rows=rows)
                    target = max(0, int(round(self._f(qty))) - others)
                except Exception:
                    target = qty
            r = self.reconcile(sleeve, sym, target, price, reason=reason)
            if r.get("status") not in ("SLEEVE_LEDGER_NOOP",):
                out.append(r)
                if armed:
                    rows = self._read()      # refresh after a write so later legs see this leg's lots
        return {"status": "SLEEVE_LEDGER_RECONCILED", "sleeve": sleeve, "events": out}

    def status(self, sleeve=None):
        rows = self._read()
        closes = [r for r in rows if r.get("kind") == "close" and (sleeve is None or r.get("sleeve") == sleeve)]
        by = {}
        for r in closes:
            b = by.setdefault(r.get("sleeve"), {"closes": 0, "realized_total": 0.0})
            b["closes"] += 1
            b["realized_total"] = round(b["realized_total"] + self._f(r.get("realized_pnl")), 2)
        open_lots = [r for r in rows if r.get("kind") == "lot" and self._f(r.get("remaining")) > 0
                     and (sleeve is None or r.get("sleeve") == sleeve)]
        return {"timestamp": datetime.utcnow().isoformat(), "status": "SLEEVE_TRADE_LEDGER_STATUS",
                "closed_by_sleeve": by, "open_lot_count": len(open_lots),
                "note": "Direct-to-broker ETF sleeves' realized closes, now visible to the edge court."}
