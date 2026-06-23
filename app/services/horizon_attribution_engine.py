from datetime import datetime


class HorizonAttributionEngine:
    def _avg(self, rows, field):
        values = [float(x.get(field) or 0) for x in rows]
        return round(sum(values) / len(values), 4) if values else 0

    def _bucket(self, rows, key_name):
        buckets = {}

        for row in rows or []:
            key = row.get(key_name) or "UNKNOWN"
            buckets.setdefault(key, []).append(row)

        output = []

        for key, items in buckets.items():
            wins = [x for x in items if x.get("prediction_correct")]
            losses = [x for x in items if not x.get("prediction_correct")]

            output.append({
                key_name: key,
                "samples": len(items),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": round((len(wins) / len(items)) * 100, 2) if items else 0,
                "average_directional_return_pct": self._avg(items, "directional_return_pct"),
                "average_win_return_pct": self._avg(wins, "directional_return_pct"),
                "average_loss_return_pct": self._avg(losses, "directional_return_pct"),
            })

        return sorted(
            output,
            key=lambda x: x.get("average_directional_return_pct", 0),
            reverse=True,
        )

    def evaluate(self, one_hour_performance):
        rows = one_hour_performance.get("latest_scored") or []

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "engine": "HorizonAttributionEngine",
            "horizon": "ONE_HOUR",
            "sample_count": len(rows),
            "symbol_attribution": self._bucket(rows, "symbol"),
            "direction_attribution": self._bucket(rows, "directional_bias"),
            "candidate_result_attribution": self._bucket(rows, "candidate_result"),
            "status": "HORIZON_ATTRIBUTION_READY",
        }
