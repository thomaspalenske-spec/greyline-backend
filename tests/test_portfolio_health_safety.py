import main


def _health():
    for route in main.app.routes:
        if route.path == "/portfolio-health":
            return route.endpoint()
    return None


def test_portfolio_health_never_enables_execution():
    """The genuine safety property this test was named for."""
    result = _health()
    assert result is not None
    assert result.get("execution_enabled") is not True


def test_health_tracks_integrity_instead_of_asserting_it():
    """Previously asserted portfolio_healthy is True unconditionally.

    Portfolio health is derived from PortfolioIntegrityEngine, whose verdict was a
    tautology — both possible input statuses were allowlisted, so it could never report a
    problem, including when no snapshot existed at all. Asserting True here locked that in.
    Health must now FOLLOW integrity rather than be assumed.
    """
    result = _health()
    assert result is not None
    assert result.get("portfolio_healthy") == result.get("integrity_healthy"), \
        "health must not claim healthy while integrity reports otherwise"
    if result.get("portfolio_healthy") is True:
        assert result.get("status") == "PORTFOLIO_HEALTHY"
    else:
        assert result.get("status") != "PORTFOLIO_HEALTHY"
