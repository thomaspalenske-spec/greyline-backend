import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def test_application_registers_get_routes():
    get_routes = [
        route.path
        for route in main.app.routes
        if hasattr(route, "methods") and "GET" in route.methods
    ]

    assert "/" in get_routes
    assert "/readiness" in get_routes
    assert len(get_routes) > 0


def test_critical_safe_get_routes_return_non_empty_dicts():
    safe_routes = {
        "/": None,
        "/readiness": None,
        "/tradestation-status": None,
        "/tradestation-oauth-readiness": None,
        "/portfolio-schema": None,
        "/portfolio-snapshot-model": None,
    }

    failed = []

    for route in main.app.routes:
        if route.path not in safe_routes:
            continue

        try:
            result = route.endpoint()

            if result is None:
                failed.append((route.path, "returned None"))
                continue

            if hasattr(result, "model_dump"):
                result = result.model_dump()
            elif hasattr(result, "dict"):
                result = result.dict()
            elif hasattr(result, "__dict__"):
                result = result.__dict__

            if not isinstance(result, dict):
                failed.append((route.path, f"returned {type(result).__name__}"))
                continue

            if len(result) == 0:
                failed.append((route.path, "returned empty dict"))

        except Exception as error:
            failed.append((route.path, str(error)))

    assert failed == []
