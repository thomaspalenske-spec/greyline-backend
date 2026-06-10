import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.governance_health_engine import GovernanceHealthEngine


def test_governance_health_green():
    result = GovernanceHealthEngine().calculate_health(
        integrity_pass=True,
        reconciliation_status="PASS",
        lifecycle_valid=True,
        drift_detected=False,
        snapshot_valid=True
    )

    assert result["health_score"] == 100
    assert result["health_level"] == "GREEN"
    assert result["status"] == "GOVERNANCE_HEALTHY"


def test_governance_health_yellow():
    result = GovernanceHealthEngine().calculate_health(
        integrity_pass=False,
        reconciliation_status="PASS",
        lifecycle_valid=True,
        drift_detected=False,
        snapshot_valid=True
    )

    assert result["health_score"] == 75
    assert result["health_level"] == "YELLOW"


def test_governance_health_red():
    result = GovernanceHealthEngine().calculate_health(
        integrity_pass=False,
        reconciliation_status="FAIL",
        lifecycle_valid=False,
        drift_detected=True,
        snapshot_valid=False
    )

    assert result["health_score"] == 0
    assert result["health_level"] == "RED"
    assert result["status"] == "GOVERNANCE_DEGRADED"
