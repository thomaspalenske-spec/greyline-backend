import main


def test_portfolio_state_is_safe_and_read_only():
    result = None

    for route in main.app.routes:
        if route.path == "/portfolio-state":
            result = route.endpoint()

    assert result is not None
    assert result.get("execution_enabled") is False
    assert result.get("status") in [
        "PORTFOLIO_STATE_ACTIVE",
        "NO_SNAPSHOT_FOUND"
    ]
