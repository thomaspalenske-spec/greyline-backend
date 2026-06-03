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

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "timeline_found": True,
            "timeline_points": len(timeline),
            "latest_point": timeline[-1] if timeline else None,
            "execution_enabled": False,
            "status": "EQUITY_TIMELINE_LOADED"
        }
