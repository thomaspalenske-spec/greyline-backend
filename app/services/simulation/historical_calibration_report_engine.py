from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.services.simulation.historical_opportunity_scoring_engine import HistoricalOpportunityScoringEngine


class HistoricalCalibrationReportEngine:
    """
    Simulator-only calibration report.

    Purpose:
      Identify which historical component scores are suppressing EXECUTE signals.
      No production GreyLine engines are modified.
    """

    def run(self, symbol="QQQ", start_date="2024-01-01", end_date="2024-12-31"):
        engine = HistoricalOpportunityScoringEngine()

        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        score_keys = [
            "composite_score",
            "bullish_score",
            "bearish_score",
            "setup_score",
            "bullish_setup_score",
            "bearish_setup_score",
            "regime_score",
            "bear_regime_score",
            "volatility_score",
            "expected_value_score",
            "trend_persistence_score",
            "breadth_score",
            "institutional_sponsorship_score",
            "asymmetry_score",
            "risk_state_score",
            "direction_confidence",
        ]

        values = defaultdict(list)
        blockers = Counter()
        results = Counter()
        option_types = Counter()
        weak_components = Counter()
        top_watch = []

        d = start
        while d <= end:
            r = engine.score_universe_snapshot([symbol], d.isoformat())

            for o in r.get("opportunities", []):
                results[o.get("result")] += 1
                option_types[o.get("option_type")] += 1

                for b in o.get("execution_blockers") or []:
                    blockers[b] += 1

                for k in score_keys:
                    v = o.get(k)
                    if isinstance(v, (int, float)):
                        values[k].append(v)

                if o.get("result") == "WATCH":
                    if o.get("option_type") == "CALL":
                        directional_keys = [
                            "bullish_score",
                            "setup_score",
                            "bullish_setup_score",
                            "regime_score",
                            "volatility_score",
                            "expected_value_score",
                            "trend_persistence_score",
                            "breadth_score",
                            "institutional_sponsorship_score",
                            "asymmetry_score",
                            "risk_state_score",
                        ]
                    else:
                        directional_keys = [
                            "bearish_score",
                            "bearish_setup_score",
                            "bear_regime_score",
                            "volatility_score",
                            "expected_value_score",
                            "trend_persistence_score",
                            "breadth_score",
                            "institutional_sponsorship_score",
                            "asymmetry_score",
                            "risk_state_score",
                        ]

                    weak = sorted(
                        [
                            (k, o.get(k))
                            for k in directional_keys
                            if isinstance(o.get(k), (int, float))
                        ],
                        key=lambda x: x[1],
                    )[:3]

                    for k, _ in weak:
                        weak_components[k] += 1

                    top_watch.append({
                        "date": d.date().isoformat(),
                        "option_type": o.get("option_type"),
                        "score": o.get("composite_score"),
                        "weakest_components": weak,
                        "execution_blockers": o.get("execution_blockers"),
                    })

            d += timedelta(days=1)

        component_ranges = {}
        for k, arr in values.items():
            if arr:
                component_ranges[k] = {
                    "min": round(min(arr), 2),
                    "avg": round(sum(arr) / len(arr), 2),
                    "max": round(max(arr), 2),
                }

        top_watch = sorted(top_watch, key=lambda x: x.get("score") or 0, reverse=True)[:25]

        return {
            "system": "GreyLine",
            "engine": "HistoricalCalibrationReportEngine",
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "result_counts": dict(results),
            "option_type_counts": dict(option_types),
            "execution_blockers": dict(blockers.most_common()),
            "weak_component_counts": dict(weak_components.most_common()),
            "component_ranges": component_ranges,
            "top_watch_candidates": top_watch,
            "future_visible": False,
            "status": "HISTORICAL_CALIBRATION_REPORT_READY",
        }
