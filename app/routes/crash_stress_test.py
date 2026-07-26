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
