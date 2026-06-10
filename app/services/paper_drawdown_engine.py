from datetime import datetime

from app.services.paper_equity_timeline_engine import (
    PaperEquityTimelineEngine
)


class PaperDrawdownEngine:

    def calculate(self):
        timeline = (
            PaperEquityTimelineEngine()
            .build_timeline()
            .get("timeline", [])
        )

        peak_equity = 0
        max_drawdown_pct = 0

        for point in timeline:

            equity = point.get("equity", 0)

            if equity > peak_equity:
                peak_equity = equity

            if peak_equity > 0:
                drawdown_pct = (
                    (peak_equity - equity)
                    / peak_equity
                ) * 100

                if drawdown_pct > max_drawdown_pct:
                    max_drawdown_pct = drawdown_pct

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "peak_equity": peak_equity,
            "max_drawdown_pct": round(
                max_drawdown_pct,
                2
            ),
            "status": "DRAWDOWN_ANALYSIS_READY"
        }
