"""Per-sleeve position ledger — the source of truth for WHICH sleeve owns WHICH shares, so overlapping
sleeves can run live without fighting over shared instruments.

The problem it fixes (2026-08-04): every sleeve sizes against the BROKER's TOTAL position for a symbol
(_held). That only works while sleeve universes are DISJOINT (low-vol's USMV/SPLV/EFAV/XMLV are unique).
The cross-sectional-momentum sleeve's cross-asset ETF universe OVERLAPS the trend basket (QQQM/IWM/EFA/DBC),
so broker-total sizing would make it liquidate trend's shares — and trend would sell its shares back. The
fix is to size each sleeve against ITS OWN position, not the broker total.

DESIGN: order-based per-sleeve accounting. A sleeve `record()`s its own confirmed fills (+buy/-sell) into a
per-sleeve tally; it `effective_held()`s against that tally (not the broker) when per-sleeve sizing is armed.
The broker holds the SUM; each sleeve manages only its own delta. `reconcile_total()` surfaces drift (sum of
sleeve tallies vs broker total per symbol) — a monitor, since order-based recording is optimistic (a resting
limit that never fills would leave the tally ahead of the broker until the next cycle corrects).

GATED: `effective_held` returns the BROKER qty (byte-identical to today) unless GREYLINE_PER_SLEEVE_SIZING is
armed — so this ships dark. Arming it live requires SEEDING the ledger with current holdings first (attribute
existing broker shares to their sleeves), then dry-run-validating; that cutover is deliberate, not automatic.
"""

import json
from datetime import datetime
from os import getenv
from pathlib import Path


class SleevePositionLedgerEngine:

    STATE = Path("app/data/state/sleeve_positions.json")

    @staticmethod
    def armed():
        """When true, sleeves size against their OWN recorded position instead of the broker total."""
        return (getenv("GREYLINE_PER_SLEEVE_SIZING", "") or "").strip().lower() == "true"

    @classmethod
    def _load(cls):
        try:
            d = json.loads(cls.STATE.read_text())
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _save(cls, d):
        try:
            cls.STATE.parent.mkdir(parents=True, exist_ok=True)
            cls.STATE.write_text(json.dumps(d, indent=2, sort_keys=True))
        except Exception:
            pass

    @classmethod
    def position(cls, sleeve, symbol):
        return int(cls._load().get(sleeve, {}).get(str(symbol).upper(), 0))

    @classmethod
    def record(cls, sleeve, symbol, signed_delta):
        """Add a CONFIRMED fill to the sleeve's tally (+buy / -sell). Call after place_order returns ok.
        A tally that reaches 0 is pruned. No-op on a zero delta."""
        try:
            delta = int(signed_delta)
        except (TypeError, ValueError):
            return {"status": "SLEEVE_POS_BAD_DELTA"}
        if delta == 0:
            return {"status": "SLEEVE_POS_NOOP"}
        d = cls._load()
        sym = str(symbol).upper()
        book = d.setdefault(sleeve, {})
        book[sym] = int(book.get(sym, 0)) + delta
        if book[sym] == 0:
            book.pop(sym, None)
        if not book:
            d.pop(sleeve, None)
        cls._save(d)
        return {"status": "SLEEVE_POS_RECORDED", "sleeve": sleeve, "symbol": sym, "position": int(book.get(sym, 0))}

    @classmethod
    def effective_held(cls, sleeve, symbol, broker_qty):
        """The quantity a sleeve should SIZE against. Armed -> this sleeve's SHARE of the CURRENT broker
        position = the FRESH broker total (broker_qty, passed in from a live positions read) MINUS what
        every OTHER sleeve confirmed-holds. Disarmed -> the broker total (byte-identical to legacy).

        WHY fresh-total-minus-others, not the sleeve's own confirmed held_qty: held_qty is updated by a
        reconcile that runs AFTER sizing, so it LAGS a cycle — it reads stale-LOW right after a fill, which
        makes delta = target - held explode and the sleeve STACK orders (the 2026-08-06 12x over-deploy).
        broker_qty is the live total and can't read stale-low; subtracting other sleeves' confirmed holds
        gives this sleeve's share without the lag. `others` is small/stable, so its own reconcile lag is a
        minor error, and the hard BookDeploymentCap backstops any residual. In-flight adds the unfilled part."""
        if not cls.armed():
            return broker_qty
        try:
            from app.services.sleeve_trade_ledger_engine import SleeveTradeLedgerEngine
            others = int(SleeveTradeLedgerEngine().held_qty_excluding(sleeve, symbol))
            return max(0, int(round(float(broker_qty))) - others)
        except Exception:
            return broker_qty        # fail SAFE to the legacy broker total rather than a wrong 0

    @classmethod
    def seed(cls, sleeve, holdings):
        """One-time migration helper: attribute existing broker shares to a sleeve before arming, so the
        first armed cycle doesn't see 0 and re-buy on top of shares it already owns. {symbol: qty}."""
        d = cls._load()
        book = d.setdefault(sleeve, {})
        for sym, q in (holdings or {}).items():
            qi = int(q)
            if qi:
                book[str(sym).upper()] = qi
        cls._save(d)
        return {"status": "SLEEVE_POS_SEEDED", "sleeve": sleeve, "count": len(book)}

    @classmethod
    def reconcile_total(cls, broker_by_symbol):
        """Sum of all sleeve tallies vs the broker total per symbol. Surfaces drift (order-based recording
        is optimistic); a monitor, not an auto-corrector. broker_by_symbol: {SYMBOL: qty}."""
        d = cls._load()
        ledger_total = {}
        for book in d.values():
            for sym, q in book.items():
                ledger_total[sym] = ledger_total.get(sym, 0) + int(q)
        broker = {str(k).upper(): int(v) for k, v in (broker_by_symbol or {}).items()}
        syms = set(ledger_total) | set(broker)
        drift = {s: {"ledger": ledger_total.get(s, 0), "broker": broker.get(s, 0)}
                 for s in syms if ledger_total.get(s, 0) != broker.get(s, 0)}
        return {"timestamp": datetime.utcnow().isoformat(), "armed": cls.armed(),
                "in_sync": not drift, "drift": drift,
                "status": "SLEEVE_POS_IN_SYNC" if not drift else "SLEEVE_POS_DRIFT"}

    @classmethod
    def status(cls):
        d = cls._load()
        return {"timestamp": datetime.utcnow().isoformat(), "armed": cls.armed(),
                "sleeves": {s: dict(book) for s, book in d.items()},
                "note": ("Per-sleeve position accounting. effective_held() sizes each sleeve against its own "
                         "shares when GREYLINE_PER_SLEEVE_SIZING is armed — lets overlapping sleeves run "
                         "live without fighting over shared instruments. Ships dark (disarmed)."),
                "status": "SLEEVE_POSITION_LEDGER_STATUS"}
