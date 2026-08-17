"""Trailing-horizon return for the mission book (e.g. 24-hour return %).

The dashboard shows Total Return (since inception). This adds a rolling 24h return without depending on
the plot timeline (which is currently unpopulated). It maintains its OWN compact mission-equity history,
fed by /account-summary on each poll: append the current HEALTHY equity (throttled so the file stays
small), prune to a bounded window, then measure current-vs-24h-ago.

HONESTY: returns None (never a fabricated baseline) until a sample genuinely ~24h old exists — the
dashboard renders "—" while it accumulates. The 24h return is measured against the equity 24h ago, not
the inception base, so it answers "how did the book move in the last day".
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


class AccountReturnHorizonEngine:

    FILE = Path("app/data/state/account_equity_history.json")
    HORIZON_HOURS = 24
    RETENTION_HOURS = 72             # keep 3 days; bounded growth, enough for a 24h window + slack
    MIN_BASELINE_AGE_HOURS = 20      # a baseline must be at least ~20h old before a "24h" figure is honest
    MAX_BASELINE_AGE_HOURS = 30      # ...and no older than ~30h, else it isn't a 24h window
    MIN_SAMPLE_SPACING_MIN = 5       # throttle appends so dense dashboard polling can't bloat the file

    def _load(self):
        try:
            d = json.loads(self.FILE.read_text())
            return d if isinstance(d, list) else []
        except Exception:
            return []

    def _save(self, points):
        try:
            self.FILE.parent.mkdir(parents=True, exist_ok=True)
            self.FILE.write_text(json.dumps(points))
        except Exception:
            pass

    @staticmethod
    def _dt(v):
        try:
            return datetime.fromisoformat(str(v))
        except Exception:
            return None

    def record_and_measure(self, equity, now=None):
        """Append the current mission equity (throttled), prune, and return the 24h-return dict. Pass the
        HEALTHY mission equity only; on a degraded read call measure_only() so no bogus sample is written."""
        now = now or datetime.utcnow()
        points = self._load()

        add = equity is not None
        if add and points:
            last_t = self._dt(points[-1].get("t"))
            if last_t is not None and (now - last_t).total_seconds() < self.MIN_SAMPLE_SPACING_MIN * 60:
                add = False           # too soon since the last sample — measure but don't append
        if add:
            points.append({"t": now.isoformat(), "e": round(float(equity), 2)})

        cutoff = now - timedelta(hours=self.RETENTION_HOURS)
        points = [p for p in points if (self._dt(p.get("t")) or cutoff) >= cutoff]
        self._save(points)
        return self._measure(points, equity, now)

    def measure_only(self, equity, now=None):
        """Measure the 24h return against stored history WITHOUT recording (use on a degraded read)."""
        now = now or datetime.utcnow()
        return self._measure(self._load(), equity, now)

    def _measure(self, points, current_equity, now):
        target = now - timedelta(hours=self.HORIZON_HOURS)
        lo = now - timedelta(hours=self.MAX_BASELINE_AGE_HOURS)
        hi = now - timedelta(hours=self.MIN_BASELINE_AGE_HOURS)

        best_t = best_e = None
        best_gap = None
        for p in points:
            t, e = self._dt(p.get("t")), p.get("e")
            try:
                e = float(e)
            except (TypeError, ValueError):
                continue
            if t is None or e <= 0 or not (lo <= t <= hi):
                continue
            gap = abs((t - target).total_seconds())
            if best_gap is None or gap < best_gap:
                best_t, best_e, best_gap = t, e, gap

        if best_e is None or current_equity is None:
            return {"return_24h_pct": None, "baseline_equity": None, "baseline_as_of": None,
                    "samples": len(points), "reason": "accumulating ~24h of equity history"}
        return {
            "return_24h_pct": round(100 * (float(current_equity) - best_e) / best_e, 2),
            "baseline_equity": round(best_e, 2),
            "baseline_as_of": best_t.isoformat(),
            "samples": len(points),
        }
