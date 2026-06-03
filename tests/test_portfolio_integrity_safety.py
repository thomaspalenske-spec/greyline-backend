import main


def test_portfolio_integrity_is_safe():
    result = None

    for route in main.app.routes:
        if route.path == "/portfolio-integrity":
            result = route.endpoint()

    assert result is not None
    assert result.get("integrity_healthy") is True
    assert result.get("execution_enabled") is False
    assert result.get("status") == "PORTFOLIO_INTEGRITY_HEALTHY"
