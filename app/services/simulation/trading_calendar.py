from datetime import datetime, timedelta

class TradingCalendar:
    def __init__(self, start_date: str, end_date: str):
        self.start_date = datetime.fromisoformat(start_date)
        self.end_date = datetime.fromisoformat(end_date)
        self.dates = self._build()

    def _build(self):
        out = []
        d = self.start_date
        while d <= self.end_date:
            if d.weekday() < 5:
                out.append(d)
            d += timedelta(days=1)
        return out

    def __iter__(self):
        return iter(self.dates)

    def __len__(self):
        return len(self.dates)
