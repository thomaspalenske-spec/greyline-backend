"""Re-baseline the mission book to a clean $10k / 0-realized starting point — an operator reset.

The operator asked to go back to 0 positions and $10k. Zeroing equity is a deliberate re-baseline of
the paper experiment (start the VRP-OS era from a known line), NOT hiding the ~$4,100 momentum loss:
the existing realized ledger is ARCHIVED to a timestamped file first, never deleted, so the real
history stays auditable. After this runs, cumulative realized = 0 and the mission equity reads
base + 0 + unrealized; once the book is also flat (see FlattenAllPositionsEngine) that is exactly
$10k / 0 positions.

daily_state is reset to the broker's CURRENT daily realized so the very next record_from_broker()
measures its delta from here — today's already-realized P&L (e.g. the flatten's fills) is not
re-booked onto the fresh ledger.

Marker-guarded: runs once per arming. Re-arm with arm() if a future reset is wanted.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine


class AccountRebaselineEngine:

    MARKER = MissionRealizedPnlEngine.DIR / "rebaseline_marker.json"
    VRP_LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")

    def _mr(self):
        return MissionRealizedPnlEngine()

    def already_done(self):
        return self.MARKER.exists()

    def arm(self):
        """Clear the completion marker so the next flat triggers another re-baseline."""
        try:
            self.MARKER.unlink()
        except FileNotFoundError:
            pass
        return {"status": "REBASELINE_ARMED"}

    def _close_open_vrp_ledger_rows(self):
        """Mark any lingering OPEN VRP ledger rows CLOSED once the broker book is flat — so the
        reality guard stays green (no phantom OPEN with no broker leg) and nothing tries to manage
        a position that no longer exists. The broker fills are what actually flattened the book."""
        led = self.VRP_LEDGER
        try:
            if not led.exists():
                return 0
            rows = [json.loads(l) for l in led.read_text().splitlines() if l.strip()]
        except Exception:
            return 0
        n = 0
        for r in rows:
            if str(r.get("status")).upper() == "OPEN":
                r["status"] = "CLOSED"
                r["closed_at"] = datetime.utcnow().isoformat()
                r["close_reason"] = "CLEAN_SLATE_FLATTEN"
                n += 1
        if n:
            with open(led, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        return n

    def rebaseline(self, reason="operator clean-slate reset"):
        """Archive the realized ledger, zero it, and reset the daily baseline. Idempotent by marker."""
        mr = self._mr()
        mr.DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        vrp_closed = self._close_open_vrp_ledger_rows()

        prior = mr.cumulative_realized()
        archived_to = None
        if mr.LEDGER.exists() and mr.LEDGER.read_text().strip():
            archived_to = str(mr.DIR / f"realized_ledger.archived-{stamp}.jsonl")
            shutil.copy2(mr.LEDGER, archived_to)
        # zero the live ledger
        mr.LEDGER.write_text("")

        # reset the daily-delta baseline to the broker's current daily realized, so the flatten's
        # own fills (already in today's broker realized) are not re-booked onto the fresh ledger
        daily = mr._broker_daily_realized()
        today = datetime.utcnow().date().isoformat()
        mr.STATE.write_text(json.dumps({"date": today, "booked_today": (daily if daily is not None else 0.0)}))

        marker = {"done_at": datetime.utcnow().isoformat(), "reason": reason,
                  "archived_realized_before": prior, "archived_to": archived_to,
                  "reset_daily_baseline_to": daily, "vrp_ledger_rows_closed": vrp_closed}
        self.MARKER.write_text(json.dumps(marker))
        return {"status": "REBASELINED", **marker, "cumulative_realized_now": mr.cumulative_realized()}

    def rebaseline_if_pending(self, reason="operator clean-slate reset"):
        """Run exactly once per arming (used by the scheduler when the book goes flat)."""
        if self.already_done():
            return {"status": "REBASELINE_ALREADY_DONE"}
        return self.rebaseline(reason=reason)
