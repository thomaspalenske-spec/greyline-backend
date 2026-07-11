from statistics import mean


class ForecastQualityLearningEngine:

    def evaluate(self, completed_rows):

        completed = [
            r for r in completed_rows
            if r.get("forecast_correct") is not None
            and r.get("return_pct") is not None
        ]

        if not completed:
            return {
                "sample_size": 0,
                "average_return_pct": 0.0,
                "average_absolute_return_pct": 0.0,
                "average_win_pct": 0.0,
                "average_loss_pct": 0.0,
                "quality_score": 0.0,
                "status": "FORECAST_QUALITY_READY",
            }

        returns = [
            float(r["return_pct"])
            for r in completed
        ]

        wins = [
            x for x in returns
            if x > 0
        ]

        losses = [
            x for x in returns
            if x <= 0
        ]

        avg_return = mean(returns)

        avg_abs = mean(
            abs(x)
            for x in returns
        )

        avg_win = (
            mean(wins)
            if wins else 0.0
        )

        avg_loss = (
            mean(losses)
            if losses else 0.0
        )

        quality = 50.0

        quality += avg_return * 3
        quality += max(
            avg_win + avg_loss,
            -15
        )

        quality = max(
            0.0,
            min(
                100.0,
                round(quality,2)
            )
        )

        return {
            "sample_size": len(completed),
            "average_return_pct": round(
                avg_return,
                4
            ),
            "average_absolute_return_pct": round(
                avg_abs,
                4
            ),
            "average_win_pct": round(
                avg_win,
                4
            ),
            "average_loss_pct": round(
                avg_loss,
                4
            ),
            "quality_score": quality,
            "status":
                "FORECAST_QUALITY_READY",
        }
