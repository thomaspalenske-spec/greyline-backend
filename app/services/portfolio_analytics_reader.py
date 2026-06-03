import json
from datetime import datetime
from pathlib import Path


class PortfolioAnalyticsReader:

    def __init__(self):
        self.latest_file = Path(
            "app/data/portfolio_analytics/latest_portfolio_analytics.json"
        )

    def read_latest(self):
        if not self.latest_file.exists():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "analytics_found": False,
                "execution_enabled": False,
                "status": "NO_PORTFOLIO_ANALYTICS_FOUND"
            }

        data = json.loads(self.latest_file.read_text())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "analytics_found": True,
            "analytics": data.get("analytics"),
            "execution_enabled": False,
            "status": "PORTFOLIO_ANALYTICS_READER_ACTIVE"
        }
