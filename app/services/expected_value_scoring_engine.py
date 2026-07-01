from datetime import datetime

from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine
from app.services.breadth_scoring_engine import BreadthScoringEngine
from app.services.setup_scoring_engine import SetupScoringEngine
from app.services.asymmetry_scoring_engine import AsymmetryScoringEngine


class ExpectedValueScoringEngine:

    def score_symbol(self, symbol, regime=None, risk=None, breadth=None, setup=None, asymmetry=None):
        symbol = symbol.upper().strip()

        regime = regime or RegimeScoringEngine().score_symbol(symbol)
        risk = risk or RiskStateScoringEngine().score_symbol(symbol)
        breadth = breadth or BreadthScoringEngine().score_symbol(symbol)
        setup = setup or SetupScoringEngine().score_symbol(symbol)
        asymmetry = asymmetry or AsymmetryScoringEngine().score_symbol(symbol)

        regime_score = regime.get("regime_score", 50)
        risk_score = risk.get("risk_state_score", 50)
        breadth_score = breadth.get("breadth_score", 50)
        setup_score = setup.get("setup_score", 50)
        bearish_setup_score = setup.get("bearish_setup_score", 100 - setup_score)
        asymmetry_score = asymmetry.get("asymmetry_score", 50)

        bear_regime_score = 100 - regime_score
        bear_breadth_score = max(35, 100 - breadth_score)
        bear_asymmetry_score = 100 - asymmetry_score

        score = round(
            (
                regime_score * 0.25
                + risk_score * 0.25
                + breadth_score * 0.20
                + setup_score * 0.15
                + asymmetry_score * 0.15
            ),
            2
        )

        if (
            regime.get("regime") == "WEAK_LIVE"
            or risk.get("risk_state") in ["DEFENSIVE", "STRESSED"]
            or breadth.get("breadth_state") == "BREADTH_WEAK_LIVE"
        ):
            score = min(score, 69)

        bearish_score = round(
            (
                bear_regime_score * 0.25
                + risk_score * 0.25
                + bear_breadth_score * 0.20
                + bearish_setup_score * 0.15
                + bear_asymmetry_score * 0.15
            ),
            2
        )

        if bearish_score >= 85:
            bearish_ev_tier = "ELITE_BEARISH_EXPECTED_VALUE_LIVE"
        elif bearish_score >= 75:
            bearish_ev_tier = "STRONG_BEARISH_EXPECTED_VALUE_LIVE"
        elif bearish_score >= 60:
            bearish_ev_tier = "DEVELOPING_BEARISH_EXPECTED_VALUE_LIVE"
        else:
            bearish_ev_tier = "WEAK_BEARISH_EXPECTED_VALUE_LIVE"

        if score >= 85:
            ev_tier = "ELITE_EXPECTED_VALUE_LIVE"
        elif score >= 75:
            ev_tier = "STRONG_EXPECTED_VALUE_LIVE"
        elif score >= 60:
            ev_tier = "DEVELOPING_EXPECTED_VALUE_LIVE"
        else:
            ev_tier = "WEAK_EXPECTED_VALUE_LIVE"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "expected_value_score": score,
            "bearish_expected_value_score": bearish_score,
            "expected_value_tier": ev_tier,
            "bearish_expected_value_tier": bearish_ev_tier,
            "ev_components": {
                "regime_score": regime_score,
                "risk_state_score": risk_score,
                "breadth_score": breadth_score,
                "setup_score": setup_score,
                "asymmetry_score": asymmetry_score,
                "bear_regime_score": bear_regime_score,
                "bear_breadth_score": bear_breadth_score,
                "bearish_setup_score": bearish_setup_score,
                "bear_asymmetry_score": bear_asymmetry_score,
            },
            "ev_context": {
                "regime": regime.get("regime"),
                "risk_state": risk.get("risk_state"),
                "breadth_state": breadth.get("breadth_state"),
                "setup_tier": setup.get("setup_tier"),
                "asymmetry_state": asymmetry.get("asymmetry_state"),
            },
            "execution_enabled": False,
            "status": "EXPECTED_VALUE_SCORE_READY"
        }
