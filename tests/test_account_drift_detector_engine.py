import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.account_drift_detector_engine import AccountDriftDetectorEngine


def test_account_drift_clear_within_tolerance():
    result = AccountDriftDetectorEngine().detect_drift(
        ledger_equity=10000.00,
        reported_equity=10000.005,
        tolerance=0.01
    )

    assert result["drift_detected"] is False
    assert result["severity"] == "CLEAR"
    assert result["execution_lockout_required"] is False


def test_account_drift_detected_above_tolerance():
    result = AccountDriftDetectorEngine().detect_drift(
        ledger_equity=10000.00,
        reported_equity=10025.00,
        tolerance=0.01
    )

    assert result["drift_detected"] is True
    assert result["severity"] == "LOW"
    assert result["execution_lockout_required"] is True


def test_account_drift_unknown_when_equity_missing():
    result = AccountDriftDetectorEngine().detect_drift(
        ledger_equity=None,
        reported_equity=10000.00
    )

    assert result["drift_detected"] is None
    assert result["severity"] == "UNKNOWN"
    assert result["execution_lockout_required"] is True
