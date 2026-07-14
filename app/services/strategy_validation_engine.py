import math
from datetime import datetime

from app.services.decision_outcome_scoring_engine import DecisionOutcomeScoringEngine

MIN_DECISIVE_SAMPLE = 30       # below this: INSUFFICIENT_DATA
DRIFT_DIVERGENCE_THRESHOLD = 0.30  # per-direction hit-rate gap that flags drift confound

FAVORABLE = "FAVORABLE_EXECUTE_SIGNAL"
UNFAVORABLE = "UNFAVORABLE_EXECUTE_SIGNAL"


def _normal_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _two_sided_p(z):
    return 2 * (1 - _normal_cdf(abs(z)))


def _wilson_ci(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (round(center - half, 4), round(center + half, 4))


def _hit(subset):
    fav = sum(1 for o in subset if o.get("score_result") == FAVORABLE)
    unf = sum(1 for o in subset if o.get("score_result") == UNFAVORABLE)
    dec = fav + unf
    return fav, unf, (fav / dec if dec else None)


class StrategyValidationEngine:
    """
    Honest validation of GreyLine's directional edge on recorded forward outcomes.

    CRITICAL measurement caveat: outcomes come from ForwardOutcomeCaptureEngine, which
    compares each decision's snapshot price to the CURRENT live price. Because decisions
    span many days but are all measured against "now", results are confounded by overall
    market drift rather than a fixed forward horizon. This engine therefore:

      - restricts to EXECUTE decisions (what the strategy actually traded),
      - checks per-direction (bullish vs bearish) hit rates, and if they diverge wildly
        (one side wins, the other loses), refuses an edge verdict and reports
        MEASUREMENT_CONFOUNDED_BY_DRIFT,
      - only renders an edge verdict when the measurement is not drift-dominated.

    A trustworthy edge answer requires the fixed-horizon grading pipeline
    (ForecastOutcomeGraderEngine) to actually grade (currently stuck), so outcomes are
    measured at a consistent forward horizon.
    """

    def validate(self, limit=5000, execute_only=True):
        scoring = DecisionOutcomeScoringEngine().score(limit=limit)
        scored = [o for o in scoring.get("scored_outcomes", []) if o.get("score_status") == "SCORED"]

        if execute_only:
            scored = [o for o in scored if str(o.get("decision", "")) == "EXECUTE"]

        favorable, unfavorable, hit_rate = _hit(scored)
        decisive = favorable + unfavorable

        bull = [o for o in scored if str(o.get("directional_bias", "")).upper() == "BULLISH"]
        bear = [o for o in scored if str(o.get("directional_bias", "")).upper() == "BEARISH"]
        _, _, bull_hr = _hit(bull)
        _, _, bear_hr = _hit(bear)

        # Drift confound: directions on opposite sides of 0.5 with a large gap means the
        # measurement is tracking market direction, not signal skill.
        drift_confounded = (
            bull_hr is not None and bear_hr is not None
            and abs(bull_hr - bear_hr) >= DRIFT_DIVERGENCE_THRESHOLD
            and ((bull_hr - 0.5) * (bear_hr - 0.5) < 0)  # straddle 0.5
        )

        moves = [o.get("move_pct") for o in scored if isinstance(o.get("move_pct"), (int, float))]
        mean_return = round(sum(moves) / len(moves), 4) if moves else None

        base = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "STRATEGY_VALIDATION",
            "measurement_method": "SNAPSHOT_TO_CURRENT_PRICE (drift-confounded; not fixed-horizon)",
            "population": "EXECUTE_ONLY" if execute_only else "ALL_SIGNALS",
            "per_direction": {
                "bullish": {"n_decisive": _hit(bull)[0] + _hit(bull)[1], "hit_rate": round(bull_hr, 4) if bull_hr is not None else None},
                "bearish": {"n_decisive": _hit(bear)[0] + _hit(bear)[1], "hit_rate": round(bear_hr, 4) if bear_hr is not None else None},
            },
            "hit_rate_test": {
                "decisive_sample": decisive,
                "favorable": favorable,
                "unfavorable": unfavorable,
                "directional_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
                "mean_directional_return_pct": mean_return,
            },
        }

        if decisive < MIN_DECISIVE_SAMPLE:
            base["verdict"] = "INSUFFICIENT_DATA"
            base["interpretation"] = (
                f"Only {decisive} decisive EXECUTE outcomes (< {MIN_DECISIVE_SAMPLE}). Not enough "
                "actually-traded signals to measure edge. Also note the measurement is drift-confounded."
            )
            base["status"] = "STRATEGY_VALIDATION_READY"
            return base

        if drift_confounded:
            base["verdict"] = "MEASUREMENT_CONFOUNDED_BY_DRIFT"
            base["interpretation"] = (
                f"Bullish hit-rate {bull_hr:.1%} vs bearish {bear_hr:.1%} — the two sides land on "
                "opposite sides of chance, which means the outcome measure is tracking market drift "
                "(snapshot-to-today), not signal skill. Edge is INDETERMINATE until outcomes are graded "
                "at a fixed forward horizon (fix ForecastOutcomeGraderEngine)."
            )
            base["status"] = "STRATEGY_VALIDATION_READY"
            return base

        z = (hit_rate - 0.5) / math.sqrt(0.25 / decisive)
        p_value = _two_sided_p(z)
        base["hit_rate_test"]["z_score"] = round(z, 4)
        base["hit_rate_test"]["p_value_two_sided"] = p_value
        base["hit_rate_test"]["wilson_ci_95"] = _wilson_ci(favorable, decisive)

        if p_value < 0.05 and hit_rate > 0.5:
            base["verdict"] = "EDGE_CONFIRMED"
            base["interpretation"] = f"Hit rate {hit_rate:.1%} significantly above chance (p={p_value:.2e})."
        elif p_value < 0.05 and hit_rate < 0.5:
            base["verdict"] = "SIGNIFICANT_INVERSE_SIGNAL"
            base["interpretation"] = f"Hit rate {hit_rate:.1%} significantly below chance (p={p_value:.2e})."
        else:
            base["verdict"] = "NO_SIGNIFICANT_EDGE"
            base["interpretation"] = f"Hit rate {hit_rate:.1%} not significantly different from chance (p={p_value:.2f})."

        base["status"] = "STRATEGY_VALIDATION_READY"
        return base
