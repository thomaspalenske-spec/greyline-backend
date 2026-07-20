import main


def _integrity():
    for route in main.app.routes:
        if route.path == "/portfolio-integrity":
            return route.endpoint()
    return None


def test_portfolio_integrity_never_enables_execution():
    """The genuine safety property: whatever the integrity verdict, this endpoint must
    never report execution as enabled."""
    result = _integrity()
    assert result is not None
    assert result.get("execution_enabled") is not True


def test_integrity_is_not_healthy_when_there_is_nothing_to_verify():
    """This test previously asserted integrity_healthy is True — in an environment with no
    portfolio snapshot at all.

    That was the defect written down as the expectation. PortfolioStateEngine has exactly
    two return paths and BOTH their statuses were in the engine's allowlist, and both
    hardcode execution_enabled False, so integrity_healthy was unconditionally True. A
    missing snapshot reported PORTFOLIO_INTEGRITY_HEALTHY — "verified" when nothing was
    examined. A check that cannot fail is worse than no check, because it is trusted.
    """
    result = _integrity()
    assert result is not None

    if result.get("snapshot_found") is True and result.get("state_valid") is True:
        assert result.get("integrity_healthy") is True
        assert result.get("status") == "PORTFOLIO_INTEGRITY_HEALTHY"
        assert result.get("failures") == []
    else:
        # Nothing to verify, or a state that is not ACTIVE -> must NOT read as healthy,
        # and must say why.
        assert result.get("integrity_healthy") is False
        assert result.get("status") == "PORTFOLIO_INTEGRITY_ERROR"
        assert result.get("failures"), "an unhealthy verdict must carry its reasons"


def test_missing_snapshot_is_reported_as_a_failure_not_ignored():
    """snapshot_found was computed, published, and then excluded from the verdict — the one
    signal that could distinguish 'verified' from 'there was nothing to verify'."""
    result = _integrity()
    if result.get("snapshot_found") is False:
        assert any("NO_PORTFOLIO_SNAPSHOT" in f for f in result.get("failures") or []), \
            result.get("failures")
