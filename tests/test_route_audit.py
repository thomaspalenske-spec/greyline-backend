import main


def test_all_get_routes_execute():
    failed = []

    ignored_routes = {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/tradestation-token-exchange",
        "/tradestation-account-discovery-live",
        "/portfolio-equity-timeline-record",
        "/live-portfolio-health",
        "/live-portfolio-snapshot-persist",
        "/live-portfolio-snapshot",
        "/tradestation-orders-live",
        "/tradestation-positions-live",
        "/tradestation-balance-live",
        "/tradestation-positions-retry",
        "/tradestation-balance-retry",
    }

    for route in main.app.routes:
        if not hasattr(route, "methods"):
            continue

        if "GET" not in route.methods:
            continue

        if route.path in ignored_routes:
            continue

        try:
            route.endpoint()
        except Exception as error:
            failed.append((route.path, str(error)))

    assert failed == []
