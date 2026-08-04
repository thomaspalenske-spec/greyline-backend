from datetime import datetime

from app.services.portfolio_summary_engine import PortfolioSummaryEngine


class PortfolioAlertEngine:

    def evaluate_alerts(self):
        summary = PortfolioSummaryEngine().get_summary()

        alerts = []

        # Distinguish a real breach from an UNKNOWN (failed/partial summary read). `is not False` treated
        # a missing/None value as a breach — so a degraded summary manufactured a CRITICAL "execution
        # enabled" on a value that was merely unknown. Alarm only on the actual breach; surface unknown
        # as its own honest state.
        if summary.get("execution_enabled") is True:
            alerts.append({
                "severity": "CRITICAL",
                "type": "EXECUTION_ENABLED",
                "message": "Execution is enabled unexpectedly."
            })
        elif summary.get("execution_enabled") is None:
            alerts.append({
                "severity": "WARNING",
                "type": "EXECUTION_STATE_UNKNOWN",
                "message": "Execution-enabled state is unknown (degraded portfolio read)."
            })

        _healthy = summary.get("overall_healthy")
        if _healthy is False:
            alerts.append({
                "severity": "HIGH",
                "type": "PORTFOLIO_HEALTH_DEGRADED",
                "message": "Portfolio health is degraded."
            })
        elif _healthy is None:
            alerts.append({
                "severity": "WARNING",
                "type": "PORTFOLIO_HEALTH_UNKNOWN",
                "message": "Portfolio health is unknown (degraded read)."
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
