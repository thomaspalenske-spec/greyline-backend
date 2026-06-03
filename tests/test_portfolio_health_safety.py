import main


def test_portfolio_health_dashboard_is_safe():
    result = None

    for route in main.app.routes:
        if route.path == "/portfolio-health":
            result = route.endpoint()

    assert result is not None
    assert result.get("portfolio_healthy") is True
    assert result.get("execution_enabled") is False
    assert result.get("status") == "PORTFOLIO_HEALTHY"
