from datetime import datetime, time
from zoneinfo import ZoneInfo


class MarketHoursEngine:
    """
    Conservative U.S. equity/options market-hours engine.
    Regular session: Mon-Fri, 9:30 AM - 4:00 PM Eastern.
    Holiday support is intentionally simple and manually extensible.
    """

    MARKET_TZ = ZoneInfo("America/New_York")

    HOLIDAYS_2026 = {
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-11-26",
        "2026-12-25",
    }

    def status(self):
        now_et = datetime.now(self.MARKET_TZ)
        date_key = now_et.date().isoformat()

        is_weekday = now_et.weekday() < 5
        is_holiday = date_key in self.HOLIDAYS_2026
        is_regular_session = (
            is_weekday
            and not is_holiday
            and time(9, 30) <= now_et.time() <= time(16, 0)
        )

        if is_holiday:
            state = "MARKET_CLOSED_HOLIDAY"
        elif not is_weekday:
            state = "MARKET_CLOSED_WEEKEND"
        elif now_et.time() < time(9, 30):
            state = "MARKET_CLOSED_PREMARKET"
        elif now_et.time() > time(16, 0):
            state = "MARKET_CLOSED_AFTER_HOURS"
        else:
            state = "MARKET_OPEN_REGULAR_SESSION"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "market_timezone": "America/New_York",
            "market_time": now_et.isoformat(),
            "date": date_key,
            "is_weekday": is_weekday,
            "is_holiday": is_holiday,
            "is_regular_session": is_regular_session,
            "state": state,
            "status": "MARKET_HOURS_STATUS_READY",
        }
