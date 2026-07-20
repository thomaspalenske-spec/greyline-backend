from datetime import datetime


class ForwardOutcomeAttributionEngine:

    # Downstream consumers reweight on these buckets and gate live PUT thresholds off them,
    # so a bucket must earn its number before it is published.
    MIN_OBSERVATIONS = 20

    def _bucket(self, outcomes, field):
        buckets = {}

        for row in outcomes or []:
            key = row.get(field) or "UNKNOWN"
            successful = row.get("successful")
            if successful is None:
                continue
            # `or 0` turned a MISSING return into a real 0.0%, dragging the mean toward
            # zero indistinguishably from a genuinely flat trade. Skip and count instead.
            raw = row.get("directional_return_pct")
            if not isinstance(raw, (int, float)):
                continue
            directional_return = float(raw)

            buckets.setdefault(key, {
                field: key,
                "observations": 0,
                "wins": 0,
                "losses": 0,
                "total_directional_return_pct": 0,
            })

            buckets[key]["observations"] += 1
            buckets[key]["total_directional_return_pct"] += directional_return

            if successful:
                buckets[key]["wins"] += 1
            else:
                buckets[key]["losses"] += 1

        rows = []
        for item in buckets.values():
            obs = item["observations"]
            rows.append({
                **item,
                # Suppressed below a minimum. A bucket with ONE resolved outcome that happened
            # to move +3% used to report win_rate_pct 100.0 and sort to the top — and
            # battlefield_adaptive_weight_advisor reads the head of this sorted list, while
            # bearish_signal_governor gates live PUT thresholds on bearish_observations<20,
            # a threshold met by ~20 re-scorings of maybe three real events.
            "win_rate_pct": (round((item["wins"] / obs) * 100, 2)
                             if obs >= self.MIN_OBSERVATIONS else None),
            "below_min_observations": obs < self.MIN_OBSERVATIONS,
                "average_directional_return_pct": (
                round(item["total_directional_return_pct"] / obs, 4)
                if obs >= self.MIN_OBSERVATIONS else None),
            })

        # Sorting by the metric put an unguarded bucket at the head of the list, which is
        # exactly where downstream advisors read. Suppressed buckets sort last.
        return sorted(rows, key=lambda x: (x["average_directional_return_pct"] is not None,
                                           x["average_directional_return_pct"] or 0),
                      reverse=True)

    def evaluate(self, outcomes=None):
        outcomes = outcomes or []
        resolved = sum(1 for r in outcomes if r.get("successful") is not None)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "ForwardOutcomeAttributionEngine",
            # sample_size counted EVERY row handed in, including PENDING and
            # PRICE_UNAVAILABLE, while the buckets count only resolved ones — so a payload
            # could read sample_size 100 with buckets summing to 4.
            "sample_size": len(outcomes),
            "resolved_count": resolved,
            "min_observations": self.MIN_OBSERVATIONS,
            "symbol_attribution": self._bucket(outcomes, "symbol"),
            "direction_attribution": self._bucket(outcomes, "directional_bias"),
            "candidate_result_attribution": self._bucket(outcomes, "candidate_result"),
            "option_type_attribution": self._bucket(outcomes, "option_type"),
            "status": "FORWARD_OUTCOME_ATTRIBUTION_READY",
        }
