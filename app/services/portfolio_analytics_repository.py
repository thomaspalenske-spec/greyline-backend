import json
from datetime import datetime
from pathlib import Path


class PortfolioAnalyticsRepository:

    def __init__(self):
        self.storage_dir = Path("app/data/portfolio_analytics")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_analytics(self, analytics):
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        analytics_file = (
            self.storage_dir /
            f"portfolio_analytics_{timestamp}.json"
        )

        payload = {
            "saved_at": datetime.utcnow().isoformat(),
            "analytics": analytics,
            "execution_enabled": False
        }

        analytics_file.write_text(
            json.dumps(payload, indent=2)
        )

        latest_file = (
            self.storage_dir /
            "latest_portfolio_analytics.json"
        )

        latest_file.write_text(
            json.dumps(payload, indent=2)
        )

        return {
            "saved": True,
            "analytics_file": str(analytics_file),
            "latest_file": str(latest_file),
            "execution_enabled": False,
            "status": "PORTFOLIO_ANALYTICS_SAVED"
        }

    def load_latest_analytics(self):
        latest_file = (
            self.storage_dir /
            "latest_portfolio_analytics.json"
        )

        if not latest_file.exists():
            return {
                "found": False,
                "execution_enabled": False,
                "status": "NO_ANALYTICS_FOUND"
            }

        return {
            "found": True,
            "data": json.loads(
                latest_file.read_text()
            ),
            "execution_enabled": False,
            "status": "PORTFOLIO_ANALYTICS_LOADED"
        }
