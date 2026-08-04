import json
from datetime import datetime
from os import getenv
from pathlib import Path

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PositionExposureLimitEngine:
    """
    Hard numeric position/exposure limits (institutional-style circuit breakers).
    A breach is a HARD block on new entries — you cannot add more risk in any
    direction until the book is reduced. Limits are env-configurable.

      GREYLINE_MAX_OPEN_POSITIONS       (default 10)
      GREYLINE_MAX_SECTOR_EXPOSURE_PCT  (default 50)

    DEGRADED-READ RESILIENCE: the ETF sleeves book straight to the broker, so a degraded broker read
    leaves real holdings unknown. Failing FULLY closed on every degraded read means a single transient
    TradeStation read flap at the open blocks a legitimate entry — which starves the very forward
    trade data the book needs. Instead, on a degraded read we fall back to the last CONFIRMED-good
    holdings IF they are still fresh (a transient flap, not a persistent outage), and evaluate the REAL
    breach thresholds against them — so an at-limit book still blocks. Only a PERSISTENT degraded read
    (no fresh snapshot) fails fully closed. The moment a good read returns, the snapshot re-syncs.
    """

    STATE_FILE = Path("app/data/state/exposure_last_good.json")
    LAST_GOOD_MAX_AGE_S_DEFAULT = 600      # 10 min: a transient TS read flap, not a persistent outage

    def _max_age_s(self):
        try:
            return float(getenv("GREYLINE_EXPOSURE_LAST_GOOD_MAX_AGE_S", "") or self.LAST_GOOD_MAX_AGE_S_DEFAULT)
        except (TypeError, ValueError):
            return self.LAST_GOOD_MAX_AGE_S_DEFAULT

    def _save_last_good(self, open_count, sector_pct):
        try:
            self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.STATE_FILE.write_text(json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "open_position_count": int(open_count),
                "max_sector_exposure_pct": float(sector_pct),
            }))
        except Exception:
            pass

    def _load_last_good(self):
        """(open_count, sector_pct, age_s) from the last CONFIRMED-good read, or None if absent or older
        than the freshness window (a persistent outage, not a transient flap)."""
        try:
            d = json.loads(self.STATE_FILE.read_text())
            age = (datetime.utcnow() - datetime.fromisoformat(str(d["timestamp"]))).total_seconds()
            if age < 0 or age > self._max_age_s():
                return None
            return int(d["open_position_count"]), float(d["max_sector_exposure_pct"]), round(age, 1)
        except Exception:
            return None

    def evaluate(self):
        max_open = int(getenv("GREYLINE_MAX_OPEN_POSITIONS", "10"))
        max_sector_pct = float(getenv("GREYLINE_MAX_SECTOR_EXPOSURE_PCT", "50"))

        degraded = False
        source = "live"
        last_good_age_s = None
        try:
            exposure = PortfolioExposureEngine().evaluate()
            open_count = int(exposure.get("open_position_count", 0) or 0)
            sector_pct = float(exposure.get("max_sector_exposure_pct", 0) or 0)
            degraded = bool(exposure.get("degraded"))
            compute_ok = not degraded
        except Exception as exc:
            open_count, sector_pct = 0, 0.0
            compute_ok = False
            degraded = True
            exposure = {"error": repr(exc)}

        if compute_ok:
            # a CONFIRMED-good read: remember it so a later transient flap can fall back to it
            self._save_last_good(open_count, sector_pct)
        else:
            # degraded/failed read: fall back to the last CONFIRMED-good holdings IF still fresh (a
            # transient TS read flap). Evaluate REAL breaches against them so an at-limit book still
            # blocks; only a PERSISTENT outage (no fresh snapshot) fails fully closed.
            lg = self._load_last_good()
            if lg is not None:
                open_count, sector_pct, last_good_age_s = lg
                compute_ok = True
                source = "last_good"

        breaches = []
        if compute_ok:
            if open_count >= max_open:
                breaches.append(f"MAX_OPEN_POSITIONS ({open_count} >= {max_open})")
            if sector_pct >= max_sector_pct:
                breaches.append(f"MAX_SECTOR_EXPOSURE_PCT ({sector_pct} >= {max_sector_pct})")

        # limits_ok is True only when we confirmed the book is within limits — from a live read OR a
        # fresh last-good snapshot. A persistent degraded read (compute_ok False) blocks new risk.
        limits_ok = compute_ok and len(breaches) == 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PositionExposureLimitEngine",
            "limits_ok": limits_ok,
            "breaches": breaches,
            "open_position_count": open_count,
            "max_open_positions": max_open,
            "max_sector_exposure_pct_observed": sector_pct,
            "max_sector_exposure_pct_limit": max_sector_pct,
            "compute_ok": compute_ok,
            "degraded": degraded,
            "source": source,                       # live | last_good
            "last_good_age_s": last_good_age_s,
            "status": "POSITION_LIMITS_BREACHED" if breaches else (
                "POSITION_LIMITS_DEGRADED" if not compute_ok else (
                    "POSITION_LIMITS_OK_LAST_GOOD" if source == "last_good" else "POSITION_LIMITS_OK"
                )
            ),
        }
