import json
from datetime import datetime
from pathlib import Path

from app.services.live_portfolio_snapshot_repository import LivePortfolioSnapshotRepository


class PortfolioEquityTimelineEngine:

    def __init__(self):
        self.timeline_dir = Path("app/data/portfolio_timeline")
        self.timeline_dir.mkdir(parents=True, exist_ok=True)
        self.timeline_file = self.timeline_dir / "equity_timeline.json"

    def record_equity_point(self):
        latest = LivePortfolioSnapshotRepository().load_latest_snapshot()

        if not latest.get("found"):
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "recorded": False,
                "execution_enabled": False,
                "status": "NO_LIVE_SNAPSHOT_FOUND"
            }

        snapshot = latest.get("data", {}).get("snapshot", {})
        balance_preview = snapshot.get("balances", {}).get("final_result", {}).get("response_preview", "")

        point = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "LIVE_PORTFOLIO_SNAPSHOT",
            "balance_response_preview_present": bool(balance_preview),
            "execution_enabled": False
        }
        # Record the ACTUAL mission equity so the timeline is a real (time, equity) series the dashboard
        # can plot — without this the points carried no equity value and any "equity curve" built from
        # them was fabricated.
        try:
            from app.services.mission_risk_governor_engine import MissionRiskGovernorEngine
            g = MissionRiskGovernorEngine().snapshot()
            eq = g.get("mission_equity")
            # Only plot equity from a HEALTHY read. On a degraded read the governor drops unrealized to 0,
            # so its equity is artificially flat — recording it would write a fake flat/dip into the
            # plotted curve. Tag the point degraded and omit the equity instead.
            if not g.get("reads_ok", True):
                point["degraded"] = True
            elif eq is not None:
                point["mission_equity"] = round(float(eq), 2)
        except Exception:
            point["degraded"] = True

        if self.timeline_file.exists():
            timeline = json.loads(self.timeline_file.read_text())
        else:
            timeline = []

        timeline.append(point)
        self.timeline_file.write_text(json.dumps(timeline, indent=2))

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "recorded": True,
            "timeline_points": len(timeline),
            "execution_enabled": False,
            "status": "EQUITY_TIMELINE_POINT_RECORDED"
        }
