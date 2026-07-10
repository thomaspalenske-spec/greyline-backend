from typing import Any, Dict

from app.services.data_providers.unusual_whales_provider import (
    UnusualWhalesProvider,
)


class UnusualWhalesBudgetGovernor:
    """
    Dynamically allocates Unusual Whales requests by daily quota usage.

    NORMAL:
        Full top-candidate institutional enrichment.

    CONSERVE:
        Enrich only WATCH or EXECUTE candidates.

    CRITICAL:
        Enrich only EXECUTE candidates.

    RESERVE_ONLY:
        No discretionary institutional enrichment.
    """

    def evaluate(self) -> Dict[str, Any]:
        usage = UnusualWhalesProvider.usage_report()

        daily_limit = usage.get("configured_daily_limit")
        request_count = usage.get("request_count") or 0
        remaining = usage.get("remaining_before_reserve")

        if not daily_limit:
            return {
                "mode": "LIMIT_UNKNOWN",
                "usage_pct": None,
                "allow_watch_enrichment": False,
                "allow_execute_enrichment": True,
                "allow_discretionary_enrichment": False,
                "usage": usage,
                "status": "UNUSUAL_WHALES_BUDGET_LIMIT_UNKNOWN",
            }

        usage_pct = round(
            (float(request_count) / float(daily_limit)) * 100,
            2,
        )

        if usage_pct < 50:
            mode = "NORMAL"
            allow_watch = True
            allow_execute = True
            allow_discretionary = True

        elif usage_pct < 70:
            mode = "CONSERVE"
            allow_watch = True
            allow_execute = True
            allow_discretionary = False

        elif usage_pct < 85:
            mode = "CRITICAL"
            allow_watch = False
            allow_execute = True
            allow_discretionary = False

        else:
            mode = "RESERVE_ONLY"
            allow_watch = False
            allow_execute = False
            allow_discretionary = False

        return {
            "mode": mode,
            "usage_pct": usage_pct,
            "request_count": request_count,
            "daily_limit": daily_limit,
            "remaining_before_reserve": remaining,
            "allow_watch_enrichment": allow_watch,
            "allow_execute_enrichment": allow_execute,
            "allow_discretionary_enrichment": allow_discretionary,
            "usage": usage,
            "status": "UNUSUAL_WHALES_BUDGET_GOVERNOR_READY",
        }

    def allow_candidate(self, candidate: Dict[str, Any]) -> bool:
        policy = self.evaluate()
        result = str(candidate.get("result") or "").upper()

        if result == "EXECUTE":
            return policy.get("allow_execute_enrichment") is True

        if result == "WATCH":
            return policy.get("allow_watch_enrichment") is True

        return policy.get("allow_discretionary_enrichment") is True
