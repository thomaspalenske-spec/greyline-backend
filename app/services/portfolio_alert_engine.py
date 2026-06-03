from datetime import datetime

from app.services.portfolio_summary_engine import PortfolioSummaryEngine


class PortfolioAlertEngine:

    def evaluate_alerts(self):
        summary = PortfolioSummaryEngine().get_summary()

        alerts = []

        if summary.get("execution_enabled") is not False:
            alerts.append({
                "severity": "CRITICAL",
                "type": "EXECUTION_ENABLED",
                "message": "Execution is enabled unexpectedly."
            })

        if summary.get("overall_healthy") is not True:
            alerts.append({
                "severity": "HIGH",
                "type": "PORTFOLIO_HEALTH_DEGRADED",
                "message": "Portfolio health is degraded."
            })

        if (
            summary.get("data_integrity_score") is not None
            and summary.get("data_integrity_score") < 90
        ):
            alerts.append({
                "severity": "MEDIUM",
                "type": "DATA_INTEGRITY_DEGRADED",
                "message": "Data integrity score dropped below threshold."
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "alerts": alerts,
            "alert_count": len(alerts),
            "execution_enabled": False,
            "status": (
                "NO_ALERTS"
                if len(alerts) == 0
                else "ALERTS_ACTIVE"
            )
        }
