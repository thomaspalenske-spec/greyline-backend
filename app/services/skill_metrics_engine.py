import math
from datetime import datetime

MIN_SAMPLE = 30


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


class SkillMetricsEngine:
    """
    Directional skill from a confusion matrix — the drift-robust, airtight answer.

    Matthews Correlation Coefficient (MCC) is 0 for ANY constant or drift-following
    predictor regardless of which way the market moved, so MCC > 0 (significantly) is
    real discriminative skill; ~0 is none; < 0 is anti-skill. Balanced accuracy and
    naive baselines (always-up / always-down = "predict the drift") are reported too.

    Confusion matrix from (directional_bias, grade):
      BULLISH + FAVORABLE   -> TP (predicted up,  actual up)
      BULLISH + UNFAVORABLE -> FP (predicted up,  actual down)
      BEARISH + FAVORABLE   -> TN (predicted down, actual down)
      BEARISH + UNFAVORABLE -> FN (predicted down, actual up)
    NEUTRAL grades (|move| < band) are excluded from the binary matrix.
    """

    GRADES = ("FAVORABLE", "UNFAVORABLE", "NEUTRAL")

    def evaluate(self, graded, effective_n=None):
        tp = fp = tn = fn = 0
        unrecognized = 0
        for x in graded:
            bias = str(x.get("directional_bias", "")).upper()
            grade = x.get("grade")
            if grade not in self.GRADES:
                # A missing or unexpected grade used to fall through to `correct = False`
                # and be tallied as a wrong prediction, so a plumbing failure that dropped
                # the field was indistinguishable from measured anti-skill — and it
                # inflated n, and therefore the significance of whatever verdict followed.
                unrecognized += 1
                continue
            if grade == "NEUTRAL":
                continue
            correct = grade == "FAVORABLE"
            if bias == "BULLISH":
                tp += 1 if correct else 0
                fp += 0 if correct else 1
            elif bias == "BEARISH":
                tn += 1 if correct else 0
                fn += 0 if correct else 1

        n = tp + fp + tn + fn
        actual_up = tp + fn
        actual_down = tn + fp

        def _safe(a, b):
            return (a / b) if b else None

        accuracy = _safe(tp + tn, n)
        tpr = _safe(tp, actual_up)     # of actual ups, predicted up (recall+)
        tnr = _safe(tn, actual_down)   # of actual downs, predicted down (recall-)
        balanced_accuracy = round((tpr + tnr) / 2, 4) if (tpr is not None and tnr is not None) else None

        denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        mcc = ((tp * tn - fp * fn) / denom) if denom else 0.0

        # Significance of MCC: z = MCC * sqrt(n), chi-square_1 = n*MCC^2, two-sided.
        #
        # n here MUST be the number of INDEPENDENT observations, not the number of rows.
        # Callers grade the same symbol repeatedly through the day over overlapping forward
        # windows, so consecutive rows share most of their outcome and rows from one cycle
        # share a single market move across symbols. Passing raw row counts understated the
        # p-value by roughly sqrt(rows per independent observation) — which is how a
        # coin-flip signal earns DIRECTIONAL_SKILL_CONFIRMED.
        #
        # `effective_n` lets a caller supply the honest count (e.g. distinct symbol-days).
        # It is capped at n because an effective sample can never exceed the actual rows.
        n_eff = n if effective_n is None else max(0, min(int(effective_n), n))
        z = mcc * math.sqrt(n_eff) if n_eff else 0.0
        p_value = 2 * (1 - _phi(abs(z)))

        base_up_acc = _safe(actual_up, n)      # always predict UP
        base_down_acc = _safe(actual_down, n)  # always predict DOWN
        best_baseline = max([b for b in (base_up_acc, base_down_acc) if b is not None], default=None)
        skill_vs_baseline = (
            round(accuracy - best_baseline, 4)
            if (accuracy is not None and best_baseline is not None) else None
        )

        # The guard applies to the EFFECTIVE sample: 500 rows that are 3 independent
        # observations is not 500 samples, and clearing MIN_SAMPLE on row count was how a
        # handful of market days could produce a confident verdict.
        if n_eff < MIN_SAMPLE:
            verdict = "INSUFFICIENT_DATA"
            interpretation = (
                f"Only {n_eff} independent decisive outcomes (< {MIN_SAMPLE}); cannot assess skill."
                + (f" {n} rows were graded, but they are not independent." if n_eff < n else "")
            )
        elif p_value < 0.05 and mcc > 0:
            verdict = "DIRECTIONAL_SKILL_CONFIRMED"
            interpretation = f"MCC {mcc:.3f} (p={p_value:.2e}) — real discriminative skill beyond drift."
        elif p_value < 0.05 and mcc < 0:
            verdict = "ANTI_SKILL"
            interpretation = f"MCC {mcc:.3f} (p={p_value:.2e}) — significantly worse than random (systematically wrong)."
        else:
            verdict = "NO_DEMONSTRABLE_SKILL"
            interpretation = (
                f"MCC {mcc:.3f} (p={p_value:.2f}) — indistinguishable from a coin flip / drift-follower. "
                "No evidence of directional edge."
            )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "SKILL_METRICS",
            "verdict": verdict,
            "interpretation": interpretation,
            "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "n_decisive": n},
            # The number the p-value was actually computed on, and how many rows were
            # discarded for having no usable grade. Both were previously invisible.
            "n_effective": n_eff,
            "unrecognized_grade_rows": unrecognized,
            "mcc": round(mcc, 4),
            "mcc_p_value": p_value,
            "accuracy": round(accuracy, 4) if accuracy is not None else None,
            "balanced_accuracy": balanced_accuracy,
            "baselines": {
                "always_up_accuracy": round(base_up_acc, 4) if base_up_acc is not None else None,
                "always_down_accuracy": round(base_down_acc, 4) if base_down_acc is not None else None,
                "best_baseline": round(best_baseline, 4) if best_baseline is not None else None,
                "strategy_edge_over_best_baseline": skill_vs_baseline,
            },
            "status": "SKILL_METRICS_READY",
        }
