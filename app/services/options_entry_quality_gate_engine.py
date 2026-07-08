from datetime import datetime


class OptionsEntryQualityGateEngine:
    def _num(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def evaluate(self, candidate_score=None, initial_contract_days=None, entry_price=None):
        score = self._num(candidate_score)
        dte = self._num(initial_contract_days)
        entry = self._num(entry_price)

        stop_loss_pct = 35.0
        tp1_pct = 50.0
        tp2_pct = 75.0

        tp1_rr = round(tp1_pct / stop_loss_pct, 2)
        tp2_rr = round(tp2_pct / stop_loss_pct, 2)

        checks = {
            "candidate_score_85_plus": score >= 85,
            "minimum_7_dte": dte >= 7,
            "entry_price_valid": entry > 0,
            "tp1_reward_risk_1_plus": tp1_rr >= 1.0,
            "tp2_reward_risk_1_5_plus": tp2_rr >= 1.5,
        }

        blockers = [k for k, v in checks.items() if not v]
        approved = len(blockers) == 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "OptionsEntryQualityGateEngine",
            "approved": approved,
            "checks": checks,
            "blockers": blockers,
            "candidate_score": score,
            "initial_contract_days": dte,
            "entry_price": entry,
            "tp1_reward_risk": tp1_rr,
            "tp2_reward_risk": tp2_rr,
            "status": "OPTIONS_ENTRY_APPROVED" if approved else "OPTIONS_ENTRY_BLOCKED",
        }
