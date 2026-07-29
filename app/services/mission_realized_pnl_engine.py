"""Cumulative realized P&L for the mission book — so a closed loss can't vanish from the equity.

The account-summary computed mission equity as base + unrealized and hard-coded realized = 0 (a
placeholder from when the account was flat). The moment a real close happened — the legacy momentum
book flattening ~$4,100 underwater — that loss disappeared: the broker's RealizedProfitLoss is a
DAILY figure that resets at the day boundary, so the next day the equity snapped back toward $10k as
if nothing was lost. This engine keeps an honest, append-only, cumulative record.

Two inputs, both auditable:
  * GOING FORWARD — each cycle, book the DELTA of the broker's daily realized P&L (GreyLine is the
    only thing trading this account, so the broker's realized IS the mission's). Delta-per-day so a
    figure that accumulates through the session and resets at midnight is booked exactly once.
  * BACKFILL — a single, explicitly-labeled entry for the legacy flatten that already occurred before
    tracking existed (its last mark, since the broker's daily realized for that day can't be re-read).

`cumulative_realized()` sums the ledger; account-summary subtracts it so the equity tells the truth.
"""

import json
from datetime import datetime
from pathlib import Path


class MissionRealizedPnlEngine:

    DIR = Path("app/data/mission_pnl")
    LEDGER = DIR / "realized_ledger.jsonl"
    STATE = DIR / "daily_state.json"

    # One-time reconstruction of the legacy momentum book's flatten (2026-07-27), which realized its
    # ~$4,100 loss before this tracking existed. Its last mark; refine against broker fills if ever
    # needed. Booked ONCE (idempotent by source tag).
    LEGACY_BACKFILL_USD = -4101.63

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _entries(self):
        try:
            return [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def _append(self, entry):
        self.DIR.mkdir(parents=True, exist_ok=True)
        with open(self.LEDGER, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def cumulative_realized(self):
        return round(sum(self._f(e.get("amount")) for e in self._entries()), 2)

    def ensure_legacy_backfill(self):
        """Book the legacy flatten once. Idempotent: skips if an entry with this source exists.

        Also skips permanently after a clean-slate re-baseline (marker present): the operator
        deliberately reset the mission line to $10k, so the archived legacy loss must NOT be
        re-injected onto the fresh ledger."""
        if (self.DIR / "rebaseline_marker.json").exists():
            return {"status": "SKIPPED_REBASELINED", "cumulative_realized": self.cumulative_realized()}
        if any(e.get("source") == "legacy_flatten_backfill" for e in self._entries()):
            return {"status": "ALREADY_BACKFILLED", "cumulative_realized": self.cumulative_realized()}
        self._append({
            "timestamp": datetime.utcnow().isoformat(),
            "amount": round(self.LEGACY_BACKFILL_USD, 2),
            "source": "legacy_flatten_backfill",
            "note": "legacy momentum book flattened 2026-07-27 (last mark); realized before tracking existed",
        })
        return {"status": "LEGACY_BACKFILLED", "amount": round(self.LEGACY_BACKFILL_USD, 2),
                "cumulative_realized": self.cumulative_realized()}

    def _broker_daily_realized(self):
        try:
            from app.services.tradestation_sim_booking_engine import TradeStationSimBookingEngine
            rj = TradeStationSimBookingEngine().balances().get("response_json") or {}
            b = (rj.get("Balances") or [rj])[0] if isinstance(rj, dict) else {}
            det = b.get("BalanceDetail") or {}
            v = det.get("RealizedProfitLoss")
            if v is None:
                v = b.get("RealizedProfitLoss")
            return None if v is None else self._f(v)
        except Exception:
            return None

    def record_from_broker(self):
        """Book the change in the broker's DAILY realized since the last read today. Delta-per-day so
        the intraday-accumulating, midnight-resetting broker figure is booked exactly once."""
        daily = self._broker_daily_realized()
        if daily is None:
            return {"status": "NO_BROKER_REALIZED", "booked": 0.0}
        today = datetime.utcnow().date().isoformat()
        try:
            state = json.loads(self.STATE.read_text())
        except Exception:
            state = {}
        booked_today = self._f(state.get("booked_today")) if state.get("date") == today else 0.0
        delta = round(daily - booked_today, 2)
        if abs(delta) >= 0.01:
            self._append({
                "timestamp": datetime.utcnow().isoformat(), "amount": delta,
                "source": "broker_daily_realized", "note": f"daily realized moved to {daily}",
            })
            self.DIR.mkdir(parents=True, exist_ok=True)
            self.STATE.write_text(json.dumps({"date": today, "booked_today": daily}))
            return {"status": "REALIZED_BOOKED", "booked": delta,
                    "cumulative_realized": self.cumulative_realized()}
        # keep the day-marker current even when nothing new booked
        if state.get("date") != today:
            self.DIR.mkdir(parents=True, exist_ok=True)
            self.STATE.write_text(json.dumps({"date": today, "booked_today": daily}))
        return {"status": "NO_CHANGE", "booked": 0.0, "cumulative_realized": self.cumulative_realized()}
