from fastapi import APIRouter

from app.services.price_bar_integrity_engine import PriceBarIntegrityEngine

router = APIRouter()


@router.get("/price-bar-integrity")
def price_bar_integrity(full: bool = False, rescan: bool = True):
    """Validate the daily price bars every signal/ATR/stop is computed from.

    ?rescan=false returns the last saved scan (fast). ?full=true scans all history
    (~3.4M rows, several seconds) instead of the recent window.
    """
    eng = PriceBarIntegrityEngine()
    if not rescan:
        return eng.last_scan() or {"status": "NO_SCAN_YET"}
    return eng.scan(full=full)
