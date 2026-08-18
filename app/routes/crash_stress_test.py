from fastapi import APIRouter

from app.services.crash_stress_test_engine import CrashStressTestEngine

router = APIRouter()


@router.get("/crash-stress-test")
def crash_stress_test():
    """The return-vs-ruin picture in dollars: the DEFENDED book (loss capped) vs the 'spectacular'
    naked/levered config (unbounded loss) across real historical vol crashes."""
    return CrashStressTestEngine().compare()


@router.get("/crash-stress-test/live")
def crash_stress_test_live():
    """Apply the crash scenarios to the LIVE book's actual net vega (defended, so bounded)."""
    return CrashStressTestEngine().stress_current_book()


@router.get("/crash-stress-test/whole-book")
def crash_stress_test_whole_book():
    """WHOLE six-sleeve book under each named crash — combines long-equity directional loss (beta x index),
    SVXY/vol_carry's non-linear short-vol crash, and the condor vega (wing-capped) into one portfolio ruin
    number. Quantifies the residual tail after the risk-parity de-concentration."""
    return CrashStressTestEngine().stress_whole_book()
