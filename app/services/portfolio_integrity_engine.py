from datetime import datetime

from app.services.portfolio_repository import PortfolioRepository
from app.services.portfolio_state_engine import PortfolioStateEngine


class PortfolioIntegrityEngine:

    def evaluate_integrity(self):
        repo = PortfolioRepository()
        latest_snapshot = repo.load_latest_snapshot()
        portfolio_state = PortfolioStateEngine().evaluate_state()

        # This check used to be a TAUTOLOGY and could not fail.
        #
        # PortfolioStateEngine.evaluate_state() has exactly two return paths, and their
        # statuses are exactly "NO_SNAPSHOT_FOUND" and "PORTFOLIO_STATE_ACTIVE" — both were
        # in the allowlist. Both also hardcode execution_enabled False. So state_valid and
        # execution_disabled were both constants and integrity_healthy was unconditionally
        # True. `snapshot_found` was computed, published, and then deliberately excluded
        # from the verdict — the one signal that could distinguish "verified" from "there
        # was nothing to verify".
        #
        # The vacuous pass was the dangerous case: no snapshot file at all yielded
        # PORTFOLIO_INTEGRITY_HEALTHY, so a dashboard or a downstream gate read the book as
        # verified when zero portfolio data existed. A check that cannot fail is worse than
        # no check, because it is trusted.
        snapshot_found = latest_snapshot.get("found") is True
        state = portfolio_state.get("status")

        # NO_SNAPSHOT_FOUND is not a healthy state — it means nothing was examined.
        state_valid = state == "PORTFOLIO_STATE_ACTIVE"
        execution_enabled = portfolio_state.get("execution_enabled")
        execution_disabled = execution_enabled is False

        failures = []
        if not snapshot_found:
            failures.append("NO_PORTFOLIO_SNAPSHOT (nothing to verify — this is not health)")
        if not state_valid:
            failures.append(f"PORTFOLIO_STATE_NOT_ACTIVE (status={state!r})")
        if not execution_disabled:
            failures.append(
                f"EXECUTION_NOT_CONFIRMED_DISABLED (execution_enabled={execution_enabled!r}; "
                "absent is not the same as False)")

        healthy = not failures

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "snapshot_found": snapshot_found,
            "state": portfolio_state.get("state"),
            "state_valid": state_valid,
            # The observed value, not a hardcoded False that made the payload agree with
            # itself regardless of what the state engine actually said.
            "execution_enabled": execution_enabled,
            "integrity_healthy": healthy,
            "failures": failures,
            "status": "PORTFOLIO_INTEGRITY_HEALTHY" if healthy else "PORTFOLIO_INTEGRITY_ERROR"
        }
