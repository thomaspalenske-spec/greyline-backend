import main


IGNORED_ROUTES = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
        "/tradestation-token-exchange",
}


def test_all_get_routes_return_non_empty_dicts():
    failed = []

    for route in main.app.routes:
        if not hasattr(route, "methods"):
            continue

        if "GET" not in route.methods:
            continue

        if route.path in IGNORED_ROUTES:
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
