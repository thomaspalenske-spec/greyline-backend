from datetime import datetime
import requests


class UnifiedReliabilityCoreEngine:
    """
    GreyLine unified reliability core.

    Read-only operational health aggregator.
    Does not place trades or modify execution state.
    """

    BASE_URL = "http://127.0.0.1:8000"

    def evaluate(self, simulate_fault=None):
        system_health = self._get("/system-health-snapshot")
        scheduler = self._get("/background-scheduler/status")
        quote_heartbeat = self._get("/fast-quote-heartbeat/status")
        token = self._get("/tradestation-token-status")

        if simulate_fault:
            system_health, scheduler, quote_heartbeat, token = self._apply_simulated_fault(
                simulate_fault,
                system_health,
                scheduler,
                quote_heartbeat,
                token,
            )

        checks = [
            self._score_system_health(system_health),
            self._score_scheduler(scheduler),
            self._score_quote_heartbeat(quote_heartbeat),
            self._score_token(token),
        ]

        score = sum(c["points"] for c in checks)

        if any(c["status"] == "RED" for c in checks):
            overall = "RED"
            summary = "ACTION_REQUIRED"
        elif any(c["status"] == "YELLOW" for c in checks):
            overall = "YELLOW"
            summary = "DEGRADED_BUT_RUNNING"
        else:
            overall = "GREEN"
            summary = "RELIABILITY_READY"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "UNIFIED_RELIABILITY_CORE",
            "overall_reliability": overall,
            "summary": summary,
            "reliability_score": score,
            "max_score": 100,
            "checks": checks,
            "source_snapshots": {
                "system_health": system_health,
                "scheduler": scheduler,
                "quote_heartbeat": quote_heartbeat,
                "token": token,
            },
            "simulate_fault": simulate_fault,
            "status": "UNIFIED_RELIABILITY_CORE_READY",
        }


    def _apply_simulated_fault(self, simulate_fault, system_health, scheduler, quote_heartbeat, token):
        fault = str(simulate_fault or "").upper().strip()

        if fault == "SCHEDULER_DOWN":
            scheduler = {
                "http_status": 200,
                "ok": True,
                "data": {
                    "scheduler_enabled": True,
                    "thread_alive": False,
                    "status": "SIMULATED_SCHEDULER_DOWN",
                },
            }

        elif fault == "QUOTE_HEARTBEAT_DOWN":
            quote_heartbeat = {
                "http_status": 200,
                "ok": True,
                "data": {
                    "enabled": True,
                    "thread_alive": False,
                    "state": {
                        "market_data_health": "SIMULATED_QUOTE_HEARTBEAT_DOWN",
                    },
                    "status": "SIMULATED_QUOTE_HEARTBEAT_DOWN",
                },
            }

        elif fault == "TOKEN_EXPIRED":
            token = {
                "http_status": 200,
                "ok": True,
                "data": {
                    "ready_for_read_only": False,
                    "token_expired": True,
                    "seconds_remaining": 0,
                    "status": "SIMULATED_TOKEN_EXPIRED",
                },
            }

        elif fault == "SYSTEM_RED":
            system_health = {
                "http_status": 200,
                "ok": True,
                "data": {
                    "overall_health": "RED",
                    "summary": "SIMULATED_SYSTEM_RED",
                    "status": "SIMULATED_SYSTEM_RED",
                },
            }

        return system_health, scheduler, quote_heartbeat, token

    def _get(self, path):
        try:
            r = requests.get(self.BASE_URL + path, timeout=5)
            return {
                "http_status": r.status_code,
                "ok": r.ok,
                "data": r.json() if r.content else {},
            }
        except Exception as e:
            return {
                "http_status": None,
                "ok": False,
                "error": str(e),
                "data": {},
            }

    def _score_system_health(self, response):
        data = response.get("data") or {}
        health = data.get("overall_health")

        if response.get("ok") and health == "GREEN":
            return {"check": "system_health", "status": "GREEN", "points": 25, "message": "system health green"}
        if response.get("ok") and health == "YELLOW":
            return {"check": "system_health", "status": "YELLOW", "points": 15, "message": "system health degraded"}
        return {"check": "system_health", "status": "RED", "points": 0, "message": "system health unavailable or red"}

    def _score_scheduler(self, response):
        data = response.get("data") or {}
        if response.get("ok") and data.get("scheduler_enabled") and data.get("thread_alive"):
            return {"check": "background_scheduler", "status": "GREEN", "points": 25, "message": "scheduler enabled and thread alive"}
        if response.get("ok") and data.get("scheduler_enabled"):
            return {"check": "background_scheduler", "status": "RED", "points": 0, "message": "scheduler enabled but thread not confirmed alive"}
        return {"check": "background_scheduler", "status": "RED", "points": 0, "message": "scheduler unavailable or disabled"}

    def _score_quote_heartbeat(self, response):
        data = response.get("data") or {}
        state = data.get("state") or {}
        market_health = state.get("market_data_health")

        if response.get("ok") and data.get("enabled") and data.get("thread_alive"):
            heartbeat_allows_execution = (
                data.get("execution_enabled") is True
                and data.get("order_placement_allowed") is True
            )

            if heartbeat_allows_execution or market_health in ["FRESH", "HEALTHY", "ACCEPTABLE", "DEGRADED", "MARKET_CLOSED_LAST_QUOTE_MARK"]:
                return {"check": "quote_heartbeat", "status": "GREEN", "points": 25, "message": market_health}

            return {"check": "quote_heartbeat", "status": "YELLOW", "points": 15, "message": market_health or "quote heartbeat running but degraded"}

        return {"check": "quote_heartbeat", "status": "RED", "points": 0, "message": "quote heartbeat unavailable or stopped"}

    def _score_token(self, response):
        data = response.get("data") or {}
        seconds_remaining = int(data.get("seconds_remaining") or 0)

        if response.get("ok") and data.get("ready_for_read_only") and not data.get("token_expired") and seconds_remaining > 300:
            return {"check": "tradestation_token", "status": "GREEN", "points": 25, "message": f"token valid with {seconds_remaining}s remaining"}
        if response.get("ok") and data.get("ready_for_read_only") and not data.get("token_expired"):
            return {"check": "tradestation_token", "status": "YELLOW", "points": 12, "message": f"token valid but near expiry: {seconds_remaining}s"}
        return {"check": "tradestation_token", "status": "RED", "points": 0, "message": "token unavailable or expired"}
