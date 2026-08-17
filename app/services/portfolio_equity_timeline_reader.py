import json
from datetime import datetime
from pathlib import Path


class PortfolioEquityTimelineReader:

    def __init__(self):
        self.timeline_file = Path("app/data/portfolio_timeline/equity_timeline.json")

    def read_timeline(self):
        if not self.timeline_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "timeline_found": False,
                "timeline_points": 0,
                "execution_enabled": False,
                "status": "NO_EQUITY_TIMELINE_FOUND"
            }

        timeline = json.loads(self.timeline_file.read_text())
        # Only points that carry a real equity value are chartable; the dashboard plots THESE or shows
        # an honest empty state — it must never fabricate a curve from points without equity.
        equity_series = [{"timestamp": p.get("timestamp"), "mission_equity": p.get("mission_equity")}
                         for p in timeline if isinstance(p, dict) and p.get("mission_equity") is not None]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "timeline_found": True,
            "timeline_points": len(timeline),
            "equity_points": len(equity_series),
            "series": equity_series,
            "latest_point": timeline[-1] if timeline else None,
            "execution_enabled": False,
            "status": "EQUITY_TIMELINE_LOADED"
        }
