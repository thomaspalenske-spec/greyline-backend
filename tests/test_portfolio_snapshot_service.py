import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def test_portfolio_snapshot_service_passes_safely():
    result = None

    for route in main.app.routes:
        if route.path == "/portfolio-snapshot-service":
            result = route.endpoint()

    assert result is not None
    assert result.get("snapshot_created") is True
    assert result.get("snapshot_loaded") is True
    assert result.get("snapshot_verified") is True
    assert result.get("execution_enabled") is False
    assert result.get("status") == "PORTFOLIO_SNAPSHOT_SERVICE_PASS"
