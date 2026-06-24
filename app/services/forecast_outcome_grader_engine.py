from datetime import datetime
import json
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine


class ForecastOutcomeGraderEngine:
    def __init__(self):
        self.outcome_path = Path("app/data/forecast_outcomes.jsonl")
        self.graded_path = Path("app/data/forecast_outcome_grades.jsonl")

    def _read_outcomes(self):
        if not self.outcome_path.exists():
            return []

        rows = []
        with self.outcome_path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _last_price(self, symbol):
        if not symbol:
            return {
                "price": None,
                "quote_status": "NO_SYMBOL",
                "trade_time": None,
            }

        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        try:
            price = float(row.get("Last") or 0)
        except Exception:
            price = 0.0

        return {
            "price": price if price > 0 else None,
            "quote_status": quote_result.get("status"),
            "trade_time": row.get("TradeTime"),
        }

    def _parse_dt(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    def _maturity(self, record, min_age_minutes=60):
        forecast_time = self._parse_dt(record.get("forecast_timestamp") or record.get("timestamp"))
        if not forecast_time:
            return {
                "forecast_age_minutes": None,
                "eligible_for_grading": False,
                "maturity_status": "FORECAST_TIMESTAMP_UNAVAILABLE",
            }

        age_minutes = round((datetime.utcnow() - forecast_time).total_seconds() / 60, 2)

        return {
            "forecast_age_minutes": age_minutes,
            "eligible_for_grading": age_minutes >= min_age_minutes,
            "maturity_status": "FORECAST_MATURED" if age_minutes >= min_age_minutes else "FORECAST_NOT_MATURED",
        }

    def grade_pending(self, market_prices=None, min_age_minutes=60):
        market_prices = market_prices or {}
        outcomes = self._read_outcomes()
        graded = []
        price_cache = {}

        for record in outcomes[-25:]:
            symbol = record.get("symbol")
            predicted_direction = record.get("predicted_direction")
            predicted_score = record.get("predicted_score")

            maturity = self._maturity(record, min_age_minutes=min_age_minutes)

            if not maturity.get("eligible_for_grading"):
                grade_record = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "forecast_id": record.get("forecast_id"),
                    "symbol": symbol,
                    "predicted_direction": predicted_direction,
                    "predicted_score": predicted_score,
                    "snapshot_price": record.get("snapshot_price"),
                    "current_price": None,
                    "return_pct": None,
                    "forecast_grade": "PENDING_FORECAST_MATURITY",
                    "forecast_correct": None,
                    "forecast_age_minutes": maturity.get("forecast_age_minutes"),
                    "eligible_for_grading": maturity.get("eligible_for_grading"),
                    "maturity_status": maturity.get("maturity_status"),
                    "status": "FORECAST_OUTCOME_GRADE_PENDING_MATURITY",
                }
                graded.append(grade_record)
                continue

            if symbol in market_prices:
                price_info = {
                    "price": market_prices.get(symbol),
                    "quote_status": "SUPPLIED_MARKET_PRICE",
                    "trade_time": None,
                }
            else:
                if symbol not in price_cache:
                    price_cache[symbol] = self._last_price(symbol)
                price_info = price_cache.get(symbol, {})

            current_price = price_info.get("price")
            snapshot_price = record.get("snapshot_price")
            forecast_correct = None
            forecast_grade = "PENDING_MARKET_PRICE"
            return_pct = None

            try:
                snapshot_price = float(snapshot_price or 0)
                current = float(current_price or 0)
            except Exception:
                snapshot_price = 0
                current = 0

            if snapshot_price > 0 and current > 0 and predicted_direction:
                raw_return_pct = round(((current - snapshot_price) / snapshot_price) * 100, 4)
                return_pct = raw_return_pct
                directional_return_pct = raw_return_pct
                if predicted_direction == "BEARISH":
                    directional_return_pct = round(-raw_return_pct, 4)

                forecast_correct = directional_return_pct > 0
                forecast_grade = "A" if directional_return_pct >= 1 else "B" if directional_return_pct > 0 else "F"

            grade_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "forecast_id": record.get("forecast_id"),
                "symbol": symbol,
                "predicted_direction": predicted_direction,
                "predicted_score": predicted_score,
                "snapshot_price": snapshot_price if snapshot_price > 0 else None,
                "current_price": current_price,
                "return_pct": return_pct,
                "forecast_grade": forecast_grade,
                "forecast_correct": forecast_correct,
                "quote_status": price_info.get("quote_status"),
                "quote_trade_time": price_info.get("trade_time"),
                "forecast_age_minutes": maturity.get("forecast_age_minutes"),
                "eligible_for_grading": maturity.get("eligible_for_grading"),
                "maturity_status": maturity.get("maturity_status"),
                "status": "FORECAST_OUTCOME_GRADED" if forecast_correct is not None else "FORECAST_OUTCOME_GRADE_PENDING",
            }

            graded.append(grade_record)

        self.graded_path.parent.mkdir(parents=True, exist_ok=True)
        with self.graded_path.open("w") as f:
            for row in graded:
                f.write(json.dumps(row) + "\n")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastOutcomeGraderEngine",
            "graded_count": len(graded),
            "grades": graded,
            "status": "FORECAST_OUTCOME_GRADER_READY",
        }
