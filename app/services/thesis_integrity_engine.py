from datetime import datetime

from app.services.expected_value_scoring_engine import ExpectedValueScoringEngine
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine


class ThesisIntegrityEngine:

    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def evaluate(self, trade):
        symbol = (trade.get("underlying") or trade.get("symbol") or "").upper().strip()

        entry_ev = self._float(trade.get("entry_expected_value_score") or trade.get("expected_value_score") or 0)
        entry_regime = self._float(trade.get("entry_regime_score") or trade.get("regime_score") or 0)
        entry_risk = self._float(trade.get("entry_risk_state_score") or trade.get("risk_state_score") or 0)

        current_regime_result = RegimeScoringEngine().score_symbol(symbol) if symbol else {}
        current_risk_result = RiskStateScoringEngine().score_symbol(symbol) if symbol else {}
        current_ev_result = ExpectedValueScoringEngine().score_symbol(
            symbol,
            regime=current_regime_result,
            risk=current_risk_result,
        ) if symbol else {}

        current_ev = self._float(current_ev_result.get("expected_value_score"), entry_ev or 50)
        current_regime = self._float(current_regime_result.get("regime_score"), entry_regime or 50)
        current_risk = self._float(current_risk_result.get("risk_state_score"), entry_risk or 50)

        if entry_ev <= 0:
            entry_ev = current_ev
        if entry_regime <= 0:
            entry_regime = current_regime
        if entry_risk <= 0:
            entry_risk = current_risk

        integrity = 100
        integrity -= abs(entry_ev - current_ev) * 0.40
        integrity -= abs(entry_regime - current_regime) * 0.30
        integrity -= abs(entry_risk - current_risk) * 0.30
        integrity = max(0, min(100, round(integrity, 2)))

        if integrity >= 80:
            status = "INTACT"
        elif integrity >= 60:
            status = "DEGRADED"
        elif integrity >= 40:
            status = "WEAK"
        else:
            status = "BROKEN"

        return {
            "thesis_integrity_engine": "ACTIVE",
            "thesis_integrity_last_calculated_at": datetime.utcnow().isoformat(),
            "thesis_integrity_score": integrity,
            "thesis_status": status,
            "thesis_symbol": symbol,
            "thesis_entry_scores": {
                "entry_expected_value_score": round(entry_ev, 2),
                "entry_regime_score": round(entry_regime, 2),
                "entry_risk_state_score": round(entry_risk, 2),
            },
            "thesis_current_scores": {
                "current_expected_value_score": round(current_ev, 2),
                "current_regime_score": round(current_regime, 2),
                "current_risk_state_score": round(current_risk, 2),
            },
            "thesis_note": "For legacy trades without stored entry thesis, current scores are used as entry baseline until future entries capture entry-time thesis.",
        }
