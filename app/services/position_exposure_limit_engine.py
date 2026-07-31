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

        degraded = False
        try:
            exposure = PortfolioExposureEngine().evaluate()
            open_count = int(exposure.get("open_position_count", 0) or 0)
            sector_pct = float(exposure.get("max_sector_exposure_pct", 0) or 0)
            # A degraded exposure read means the live broker holdings (the ETF sleeves that book
            # straight to the broker) are UNKNOWN — open_count/sector_pct were computed from the paper
            # ledgers ALONE and understate real concentration. That is NOT a confirmation the book is
            # within limits, so treat it as compute-failed rather than OK.
            degraded = bool(exposure.get("degraded"))
            compute_ok = not degraded
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

        # Fail CLOSED: this is a hard circuit breaker, so an unverifiable book (engine threw OR the
        # broker read was degraded and holdings are unknown) must BLOCK new concentration-gated risk,
        # not read as OK. limits_ok is True only when we actually confirmed the book is within limits.
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
            "status": "POSITION_LIMITS_BREACHED" if breaches else (
                "POSITION_LIMITS_DEGRADED" if not compute_ok else "POSITION_LIMITS_OK"
            ),
        }
