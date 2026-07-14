import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.skill_metrics_engine import SkillMetricsEngine


def _graded(bull_fav, bull_unf, bear_fav, bear_unf):
    # BULLISH+FAV=TP, BULLISH+UNF=FP, BEARISH+FAV=TN, BEARISH+UNF=FN
    out = []
    out += [{"directional_bias": "BULLISH", "grade": "FAVORABLE"}] * bull_fav
    out += [{"directional_bias": "BULLISH", "grade": "UNFAVORABLE"}] * bull_unf
    out += [{"directional_bias": "BEARISH", "grade": "FAVORABLE"}] * bear_fav
    out += [{"directional_bias": "BEARISH", "grade": "UNFAVORABLE"}] * bear_unf
    return out


def test_perfect_skill_mcc_1():
    # all bullish correct, all bearish correct -> perfect classifier
    r = SkillMetricsEngine().evaluate(_graded(40, 0, 40, 0))
    assert r["mcc"] == 1.0
    assert r["verdict"] == "DIRECTIONAL_SKILL_CONFIRMED"


def test_perfect_anti_skill_mcc_minus_1():
    # always wrong both directions
    r = SkillMetricsEngine().evaluate(_graded(0, 40, 0, 40))
    assert r["mcc"] == -1.0
    assert r["verdict"] == "ANTI_SKILL"


def test_drift_follower_has_zero_skill():
    # Market drifted up: every actual outcome is UP. Bullish calls win, bearish lose.
    # This is a pure drift-following pattern -> MCC must be ~0 (one matrix row empty).
    # TP=bull correct(up), FP=0, TN=0, FN=bear wrong(actual up). n=80.
    r = SkillMetricsEngine().evaluate(_graded(40, 0, 0, 40))
    assert abs(r["mcc"]) < 1e-9  # zero discriminative skill despite 50% raw accuracy
    assert r["verdict"] == "NO_DEMONSTRABLE_SKILL"
    # baseline check: always-up would have scored the "up" outcomes for free
    assert r["baselines"]["always_up_accuracy"] is not None


def test_no_skill_random_matrix():
    r = SkillMetricsEngine().evaluate(_graded(20, 20, 20, 20))
    assert abs(r["mcc"]) < 1e-9
    assert r["verdict"] == "NO_DEMONSTRABLE_SKILL"


def test_insufficient_data():
    r = SkillMetricsEngine().evaluate(_graded(3, 3, 3, 3))
    assert r["verdict"] == "INSUFFICIENT_DATA"


def test_modest_real_skill_confirmed():
    # 70% each direction, balanced -> real skill, enough n
    r = SkillMetricsEngine().evaluate(_graded(35, 15, 35, 15))
    assert r["mcc"] > 0
    assert r["verdict"] == "DIRECTIONAL_SKILL_CONFIRMED"
    assert r["baselines"]["strategy_edge_over_best_baseline"] is not None
