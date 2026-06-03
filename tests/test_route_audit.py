import main


def test_all_get_routes_execute():
    failed = []

    ignored_routes = {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/tradestation-token-exchange",
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
