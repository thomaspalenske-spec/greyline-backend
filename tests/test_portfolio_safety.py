import main


def test_portfolio_execution_disabled():
    portfolio_result = None

    for route in main.app.routes:
        if route.path == "/portfolio":
            portfolio_result = route.endpoint()

    assert portfolio_result is not None
    assert portfolio_result.get("status") == "PORTFOLIO_AGGREGATION_ACTIVE"
    assert portfolio_result.get("execution_enabled") is False
    assert portfolio_result.get("broker_connected") is False
