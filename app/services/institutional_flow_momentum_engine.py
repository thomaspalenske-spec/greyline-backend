import json
from datetime import datetime
from pathlib import Path


class InstitutionalFlowMomentumEngine:
    """
    Tracks institutional flow history by symbol and estimates whether flow is
    accelerating, fading, or stable.
    """

    _state_file = Path("app/data/runtime/institutional_flow_momentum_state.json")
    _max_points = 20

    def _load(self):
        if not self._state_file.exists():
            return {}
        try:
            return json.loads(self._state_file.read_text())
        except Exception:
            return {}

    def _save(self, state):
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(state, indent=2))

    def update(self, candidate):
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if not symbol:
            return {
                "status": "INSTITUTIONAL_FLOW_MOMENTUM_SKIPPED",
                "reason": "SYMBOL_MISSING",
            }

        state = self._load()
        history = state.get(symbol, [])

        point = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "option_type": candidate.get("option_type"),
            "result": candidate.get("result"),
            "composite_score": candidate.get("composite_score"),
            "institutional_flow_direction": candidate.get("institutional_flow_direction"),
            "institutional_flow_confidence": candidate.get("institutional_flow_confidence"),
            "institutional_conviction_score": candidate.get("institutional_conviction_score"),
            "institutional_flow_gate": candidate.get("institutional_flow_gate"),
        }

        history.append(point)
        history = history[-self._max_points:]
        state[symbol] = history
        self._save(state)

        return self._score(symbol, history)

    def _num(self, value, default=0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _score(self, symbol, history):
        if len(history) < 2:
            latest = history[-1] if history else {}
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "institutional_flow_momentum_score": 0,
                "institutional_flow_acceleration": 0,
                "institutional_flow_velocity": "INSUFFICIENT_HISTORY",
                "institutional_flow_trend": "NEW_SIGNAL",
                "institutional_flow_decay": False,
                "institutional_flow_duration": len(history),
                "institutional_flow_persistence": "UNCONFIRMED",
                "institutional_flow_momentum_context": {
                    "latest_confidence": latest.get("institutional_flow_confidence"),
                    "latest_conviction": latest.get("institutional_conviction_score"),
                    "samples": len(history),
                },
                "status": "INSTITUTIONAL_FLOW_MOMENTUM_READY",
            }

        last = history[-1]
        prev = history[-2]

        latest_conf = self._num(last.get("institutional_flow_confidence"))
        prev_conf = self._num(prev.get("institutional_flow_confidence"))
        latest_conviction = self._num(last.get("institutional_conviction_score"))
        prev_conviction = self._num(prev.get("institutional_conviction_score"))
        latest_score = self._num(last.get("composite_score"))
        prev_score = self._num(prev.get("composite_score"))

        confidence_delta = latest_conf - prev_conf
        conviction_delta = latest_conviction - prev_conviction
        score_delta = latest_score - prev_score

        momentum_score = round(
            confidence_delta * 0.45
            + conviction_delta * 0.35
            + score_delta * 0.20,
            2
        )

        if len(history) >= 3:
            prior = history[-3]
            prior_conf = self._num(prior.get("institutional_flow_confidence"))
            acceleration = round(confidence_delta - (prev_conf - prior_conf), 2)
        else:
            acceleration = round(confidence_delta, 2)

        if momentum_score >= 8:
            velocity = "ACCELERATING"
            trend = "BUILDING"
        elif momentum_score <= -8:
            velocity = "DECELERATING"
            trend = "FADING"
        else:
            velocity = "STABLE"
            trend = "HOLDING"

        decay = momentum_score <= -8

        latest_direction = last.get("institutional_flow_direction")
        persistence_count = 0
        for item in reversed(history):
            if item.get("institutional_flow_direction") == latest_direction:
                persistence_count += 1
            else:
                break

        if persistence_count >= 5:
            persistence = "PERSISTENT"
        elif persistence_count >= 3:
            persistence = "DEVELOPING"
        else:
            persistence = "EARLY"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "institutional_flow_momentum_score": momentum_score,
            "institutional_flow_acceleration": acceleration,
            "institutional_flow_velocity": velocity,
            "institutional_flow_trend": trend,
            "institutional_flow_decay": decay,
            "institutional_flow_duration": persistence_count,
            "institutional_flow_persistence": persistence,
            "institutional_flow_momentum_context": {
                "latest_confidence": latest_conf,
                "previous_confidence": prev_conf,
                "confidence_delta": round(confidence_delta, 2),
                "latest_conviction": latest_conviction,
                "previous_conviction": prev_conviction,
                "conviction_delta": round(conviction_delta, 2),
                "latest_composite_score": latest_score,
                "previous_composite_score": prev_score,
                "score_delta": round(score_delta, 2),
                "samples": len(history),
            },
            "status": "INSTITUTIONAL_FLOW_MOMENTUM_READY",
        }
