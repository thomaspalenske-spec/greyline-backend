import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict


class UnusualWhalesRefreshDecisionEngine:
    STATE_PATH = Path(
        "app/data/unusual_whales_refresh_state.json"
    )
    _lock = Lock()

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _load_state(cls) -> Dict[str, Any]:
        try:
            value = json.loads(cls.STATE_PATH.read_text())
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _write_state(cls, state: Dict[str, Any]) -> None:
        cls.STATE_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        cls.STATE_PATH.write_text(
            json.dumps(
                state,
                indent=2,
                sort_keys=True,
                default=str,
            )
        )

    @staticmethod
    def _max_age_seconds(budget_mode: str) -> int:
        return {
            "NORMAL": 900,
            "CONSERVE": 1800,
            "CRITICAL": 3600,
            "RESERVE_ONLY": 21600,
            "LIMIT_UNKNOWN": 3600,
        }.get(str(budget_mode or "").upper(), 1800)

    def evaluate(
        self,
        candidate: Dict[str, Any],
        budget_policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        symbol = str(candidate.get("symbol") or "").upper().strip()

        if not symbol:
            return {
                "refresh_allowed": False,
                "refresh_required": False,
                "reason": "SYMBOL_MISSING",
                "status": "UW_REFRESH_DECISION_INVALID",
            }

        now = datetime.now(timezone.utc)
        budget_mode = str(
            budget_policy.get("mode") or "LIMIT_UNKNOWN"
        ).upper()

        with self._lock:
            state = self._load_state()
            previous = state.get(symbol) or {}

        previous_timestamp = previous.get("refreshed_at")
        age_seconds = None

        if previous_timestamp:
            try:
                parsed = datetime.fromisoformat(
                    str(previous_timestamp).replace(
                        "Z",
                        "+00:00",
                    )
                )
                age_seconds = max(
                    0.0,
                    (now - parsed).total_seconds(),
                )
            except (TypeError, ValueError):
                age_seconds = None

        current_result = str(
            candidate.get("result") or ""
        ).upper()
        previous_result = str(
            previous.get("result") or ""
        ).upper()

        current_score = self._float(
            candidate.get("composite_score")
        )
        previous_score = self._float(
            previous.get("composite_score")
        )

        current_sponsorship = self._float(
            candidate.get("institutional_sponsorship_score")
        )
        previous_sponsorship = self._float(
            previous.get("institutional_sponsorship_score")
        )

        current_flow = str(
            candidate.get("institutional_flow_direction") or ""
        ).upper()
        previous_flow = str(
            previous.get("institutional_flow_direction") or ""
        ).upper()

        score_change = round(
            current_score - previous_score,
            2,
        )
        sponsorship_change = round(
            current_sponsorship - previous_sponsorship,
            2,
        )

        max_age_seconds = self._max_age_seconds(budget_mode)

        reasons = []

        if not previous:
            reasons.append("FIRST_OBSERVATION")

        if (
            current_result == "EXECUTE"
            and previous_result != "EXECUTE"
        ):
            reasons.append("BECAME_EXECUTE")

        if abs(score_change) >= 3:
            reasons.append("COMPOSITE_SCORE_CHANGED")

        if abs(sponsorship_change) >= 5:
            reasons.append("SPONSORSHIP_CHANGED")

        if (
            current_flow
            and previous_flow
            and current_flow != previous_flow
        ):
            reasons.append("FLOW_DIRECTION_CHANGED")

        if (
            age_seconds is None
            or age_seconds >= max_age_seconds
        ):
            reasons.append("REFRESH_STALE")

        refresh_required = bool(reasons)

        if budget_mode == "RESERVE_ONLY":
            refresh_allowed = False
            decision_reason = "DAILY_RESERVE_PROTECTED"
        elif current_result == "EXECUTE":
            refresh_allowed = refresh_required
            decision_reason = (
                reasons[0]
                if reasons
                else "EXECUTE_INTELLIGENCE_STILL_FRESH"
            )
        elif budget_mode in {"NORMAL", "CONSERVE"}:
            refresh_allowed = refresh_required
            decision_reason = (
                reasons[0]
                if reasons
                else "NO_MATERIAL_CHANGE"
            )
        else:
            refresh_allowed = False
            decision_reason = "BUDGET_MODE_RESTRICTED"

        return {
            "symbol": symbol,
            "budget_mode": budget_mode,
            "candidate_result": current_result,
            "refresh_allowed": refresh_allowed,
            "refresh_required": refresh_required,
            "reason": decision_reason,
            "reasons": reasons,
            "age_seconds": (
                round(age_seconds, 2)
                if age_seconds is not None
                else None
            ),
            "max_age_seconds": max_age_seconds,
            "composite_score_change": score_change,
            "sponsorship_score_change": sponsorship_change,
            "flow_direction_changed": (
                bool(current_flow)
                and bool(previous_flow)
                and current_flow != previous_flow
            ),
            "status": "UW_REFRESH_DECISION_READY",
        }

    def mark_refreshed(
        self,
        candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        symbol = str(candidate.get("symbol") or "").upper().strip()

        if not symbol:
            raise ValueError("symbol is required")

        record = {
            "refreshed_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "result": candidate.get("result"),
            "composite_score": self._float(
                candidate.get("composite_score")
            ),
            "institutional_sponsorship_score": self._float(
                candidate.get(
                    "institutional_sponsorship_score"
                )
            ),
            "institutional_flow_direction": candidate.get(
                "institutional_flow_direction"
            ),
        }

        with self._lock:
            state = self._load_state()
            state[symbol] = record
            self._write_state(state)

        return {
            "symbol": symbol,
            "recorded": True,
            "status": "UW_REFRESH_STATE_RECORDED",
        }
