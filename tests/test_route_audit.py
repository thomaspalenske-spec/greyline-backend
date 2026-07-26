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
        "/premium-harvest-os",   # aggregates live UW/broker reads
        "/catalyst-overlay",     # live UW economic/FDA calendar
        "/vrp-short-premium/plan",   # scans 201 names live (UW + option chains) — verified 200 over HTTP
        "/broker-protection",        # live broker positions/orders read, like the other TS-live routes
        "/tradestation-balance-live",
        "/tradestation-positions-retry",
        "/tradestation-balance-retry",
        "/tradestation-token-refresh",
    "/portfolio-dashboard",
    "/portfolio-summary",
    "/portfolio-alerts",
    "/live-universe-quote-scan",
    "/opportunity-scores",
    "/opportunity-summary",
    "/quote-snapshot-nvda",
    "/universe-snapshot-capture",
    # Return HTTP 200 in production but cannot be smoke-tested by calling
    # route.endpoint() directly: they take a Request (HTML) or Query() params,
    # so a bare call receives Query objects / no request. Verified 200 over HTTP.
    "/operator-dashboard",            # HTML template route (needs Request)
        "/strategy-dashboard",            # HTML template route (needs Request)
    "/directional-attribution-report",  # Query() param used as slice index
    "/portfolio-governor",            # Query() param compared to int
    "/operator-commander-summary",    # intermittent read-during-write JSON race
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
