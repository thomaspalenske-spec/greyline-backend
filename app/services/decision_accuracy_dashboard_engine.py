from datetime import datetime

from app.services.decision_outcome_scoring_engine import DecisionOutcomeScoringEngine


class DecisionAccuracyDashboardEngine:

    def summarize(self, limit=50):
        scoring = DecisionOutcomeScoringEngine().score(limit=limit)

        events_analyzed = scoring.get("events_analyzed", 0)
        favorable = scoring.get("favorable_count", 0)
        unfavorable = scoring.get("unfavorable_count", 0)
        neutral = scoring.get("neutral_count", 0)
        pending = scoring.get("pending_count", 0)
        skipped = scoring.get("skipped_count", 0)

        scored_total = favorable + unfavorable + neutral

        execute_signal_win_rate = None
        if scored_total > 0:
            execute_signal_win_rate = round((favorable / scored_total) * 100, 2)

        execute_signal_loss_rate = None
        if scored_total > 0:
            execute_signal_loss_rate = round((unfavorable / scored_total) * 100, 2)

        # NEUTRAL is NOT half a win. Crediting it 0.5 made the score converge to ~50
        # whenever most outcomes were flat — which, before the fixed-horizon fix, was
        # nearly always, because decisions were graded minutes after they were made and
        # could not have moved. A no-signal system therefore scored 50 and read as
        # mediocre-but-real rather than as no measurement. It also contradicted
        # execute_signal_win_rate, which keeps NEUTRAL in the denominator without
        # crediting it.
        #
        # Decisive outcomes only: of the calls that actually resolved, how many were right.
        decisive_total = favorable + unfavorable
        decision_quality_score = (
            round((favorable / decisive_total) * 100, 2) if decisive_total > 0 else None
        )

        symbol_scores = {}
        for item in scoring.get("scored_outcomes", []):
            symbol = item.get("symbol")
            if not symbol:
                continue

            if symbol not in symbol_scores:
                symbol_scores[symbol] = {
                    "symbol": symbol,
                    "favorable": 0,
                    "unfavorable": 0,
                    "neutral": 0,
                    "pending": 0,
                    "skipped": 0,
                }

            result = item.get("score_result")
            if result == "FAVORABLE_EXECUTE_SIGNAL":
                symbol_scores[symbol]["favorable"] += 1
            elif result == "UNFAVORABLE_EXECUTE_SIGNAL":
                symbol_scores[symbol]["unfavorable"] += 1
            elif result == "NEUTRAL_EXECUTE_SIGNAL":
                symbol_scores[symbol]["neutral"] += 1
            elif item.get("score_status") == "SKIPPED":
                symbol_scores[symbol]["skipped"] += 1
            else:
                symbol_scores[symbol]["pending"] += 1

        symbols = list(symbol_scores.values())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "DECISION_ACCURACY_DASHBOARD",
            "events_analyzed": events_analyzed,
            "scored_total": scored_total,
            "favorable_execute_signals": favorable,
            "unfavorable_execute_signals": unfavorable,
            "neutral_execute_signals": neutral,
            "pending_outcomes": pending,
            "skipped_outcomes": skipped,
            "execute_signal_win_rate": execute_signal_win_rate,
            "execute_signal_loss_rate": execute_signal_loss_rate,
            "decision_quality_score": decision_quality_score,
            # The denominator behind that score, and the flat calls excluded from it. A
            # score computed on a handful of decisive outcomes is not comparable to one
            # computed on hundreds, and that was previously invisible.
            "decisive_outcomes": decisive_total,
            "neutral_excluded": neutral,
            "symbol_accuracy": symbols,
            "execution_enabled": False,
            "order_placement_allowed": False,
            "status": "DECISION_ACCURACY_DASHBOARD_READY",
        }
