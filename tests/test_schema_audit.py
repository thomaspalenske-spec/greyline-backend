import main


IGNORED_ROUTES = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
        "/tradestation-token-exchange",
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
