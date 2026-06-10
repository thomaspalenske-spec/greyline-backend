import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backend_control_center_engine import BackendControlCenterEngine


def test_backend_control_center_ready_when_integrity_passes():
    with patch("app.services.backend_control_center_engine.IntegrityControlCenterEngine") as MockIntegrity:
        MockIntegrity.return_value.evaluate.return_value = {
            "integrity_pass": True,
            "status": "GREYLINE_INTEGRITY_READY"
        }

        result = BackendControlCenterEngine().get_control_center()

    assert result["backend_ready"] is True
    assert result["integrity_pass"] is True
    assert result["execution_allowed"] is False
    assert result["order_placement_allowed"] is False
    assert result["status"] == "GREYLINE_CONTROL_CENTER_READY"


def test_backend_control_center_blocks_when_integrity_fails():
    with patch("app.services.backend_control_center_engine.IntegrityControlCenterEngine") as MockIntegrity:
        MockIntegrity.return_value.evaluate.return_value = {
            "integrity_pass": False,
            "status": "GREYLINE_INTEGRITY_BLOCKED"
        }

        result = BackendControlCenterEngine().get_control_center()

    assert result["integrity_pass"] is False
    assert result["status"] == "GREYLINE_CONTROL_CENTER_BLOCKED"
