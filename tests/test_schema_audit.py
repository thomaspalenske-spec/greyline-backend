import main


IGNORED_ROUTES = {
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
    # route.endpoint() directly (Request/Query params or HTML response).
    "/operator-dashboard",
        "/strategy-dashboard",            # HTML template route (needs Request)
    "/directional-attribution-report",
    "/portfolio-governor",
    "/operator-commander-summary",
}


def normalize(result):
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "dict"):
        return result.dict()
    if hasattr(result, "__dict__"):
        return result.__dict__
    return result


def test_endpoint_schema_audit():
    failed = []

    for route in main.app.routes:

        if not hasattr(route, "methods"):
            continue

        if "GET" not in route.methods:
            continue

        if route.path in IGNORED_ROUTES:
            continue

        try:
            result = normalize(route.endpoint())

            if not isinstance(result, dict):
                failed.append((route.path, "not dict"))
                continue

            if len(result.keys()) == 0:
                failed.append((route.path, "empty schema"))

        except Exception as error:
            failed.append((route.path, str(error)))

    assert failed == []
