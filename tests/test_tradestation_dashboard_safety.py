import main


def test_tradestation_dashboard_execution_disabled():
    dashboard_result = None

    for route in main.app.routes:
        if route.path == "/tradestation-dashboard":
            dashboard_result = route.endpoint()

    assert dashboard_result is not None
    assert dashboard_result.get("broker") == "TradeStation"
    assert dashboard_result.get("execution_enabled") is False
    assert dashboard_result.get("authority_level") == "OBSERVE_RECOMMEND_ONLY"
