from datetime import datetime
from os import getenv

from app.services.portfolio_exposure_engine import PortfolioExposureEngine


class PositionExposureLimitEngine:
    """
    Hard numeric position/exposure limits (institutional-style circuit breakers).
    A breach is a HARD block on new entries — you cannot add more risk in any
    direction until the book is reduced. Limits are env-configurable.

      GREYLINE_MAX_OPEN_POSITIONS       (default 10)
      GREYLINE_MAX_SECTOR_EXPOSURE_PCT  (default 50)
    """

    def evaluate(self):
        max_open = int(getenv("GREYLINE_MAX_OPEN_POSITIONS", "10"))
        max_sector_pct = float(getenv("GREYLINE_MAX_SECTOR_EXPOSURE_PCT", "50"))

        try:
            exposure = PortfolioExposureEngine().evaluate()
            open_count = int(exposure.get("open_position_count", 0) or 0)
            sector_pct = float(exposure.get("max_sector_exposure_pct", 0) or 0)
            compute_ok = True
        except Exception as exc:
            open_count, sector_pct = 0, 0.0
            compute_ok = False
            exposure = {"error": repr(exc)}

        breaches = []
        if compute_ok:
            if open_count >= max_open:
                breaches.append(f"MAX_OPEN_POSITIONS ({open_count} >= {max_open})")
            if sector_pct >= max_sector_pct:
                breaches.append(f"MAX_SECTOR_EXPOSURE_PCT ({sector_pct} >= {max_sector_pct})")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PositionExposureLimitEngine",
            "limits_ok": len(breaches) == 0,
            "breaches": breaches,
            "open_position_count": open_count,
            "max_open_positions": max_open,
            "max_sector_exposure_pct_observed": sector_pct,
            "max_sector_exposure_pct_limit": max_sector_pct,
            "compute_ok": compute_ok,
            "status": "POSITION_LIMITS_BREACHED" if breaches else (
                "POSITION_LIMITS_DEGRADED" if not compute_ok else "POSITION_LIMITS_OK"
            ),
        }
