from datetime import datetime
import hashlib
import json
from pathlib import Path

from app.services.tradestation_quote_live_engine import (
    TradeStationQuoteLiveEngine,
)


class ForecastOutcomeCaptureEngine:
    def __init__(self):
        self.outcome_path = Path(
            "app/data/forecast_outcomes.jsonl"
        )

    def _last_price(self, symbol):
        if not symbol:
            return {
                "price": None,
                "quote_status": "NO_SYMBOL",
                "trade_time": None,
            }

        quote_result = (
            TradeStationQuoteLiveEngine().get_quote(symbol)
        )
        quotes = (
            quote_result.get("response_json") or {}
        ).get("Quotes") or []
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

    def _read_existing_ids(self, limit=500):
        if not self.outcome_path.exists():
            return set()

        ids = set()

        for line in self.outcome_path.read_text().splitlines()[-limit:]:
            try:
                row = json.loads(line)
            except Exception:
                continue

            forecast_id = row.get("forecast_id")

            if forecast_id:
                ids.add(str(forecast_id))

        return ids

    @staticmethod
    def _forecast_id(forecast):
        explicit = forecast.get("forecast_id")

        if explicit:
            return str(explicit)

        symbol = (
            forecast.get("symbol") or "UNKNOWN"
        ).upper()
        direction = (
            forecast.get("directional_bias")
            or forecast.get("predicted_direction")
            or "UNKNOWN"
        ).upper()

        score = forecast.get(
            "composite_score",
            forecast.get("score"),
        )

        try:
            score = round(float(score), 2)
        except Exception:
            score = 0.0

        now = datetime.utcnow()

        # One unique forecast per symbol/direction/score
        # within each five-minute scheduler window.
        minute_bucket = (now.minute // 5) * 5
        bucket = now.replace(
            minute=minute_bucket,
            second=0,
            microsecond=0,
        ).isoformat()

        raw = (
            f"{symbol}|{direction}|{score}|{bucket}"
        )

        digest = hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:16]

        return (
            f"{symbol}-{direction}-{bucket}-{digest}"
        )

    def capture(self, forecast):
        forecast = forecast or {}

        symbol = forecast.get("symbol")
        forecast_id = self._forecast_id(forecast)

        if forecast_id in self._read_existing_ids():
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "forecast_id": forecast_id,
                "symbol": symbol,
                "captured": False,
                "deduped": True,
                "status": "FORECAST_OUTCOME_CAPTURE_DEDUPED",
            }

        price_info = self._last_price(symbol)

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "forecast_id": forecast_id,
            "symbol": symbol,
            "predicted_direction": (
                forecast.get("directional_bias")
                or forecast.get("predicted_direction")
            ),
            "option_type": forecast.get("option_type"),
            "predicted_score": (
                forecast.get("composite_score")
                or forecast.get("score")
            ),
            "direction_confidence": forecast.get(
                "direction_confidence"
            ),
            "forecast_confidence": (
                forecast.get(
                    "institutional_calibrated_forecast_confidence"
                )
                or forecast.get(
                    "institutional_forecast_confidence"
                )
                or forecast.get("forecast_confidence")
            ),
            "snapshot_price": price_info.get("price"),
            "quote_status": price_info.get(
                "quote_status"
            ),
            "quote_trade_time": price_info.get(
                "trade_time"
            ),
            "forecast_timestamp": (
                forecast.get("timestamp")
                or datetime.utcnow().isoformat()
            ),
            "result": forecast.get("result"),
            "regime": forecast.get("regime"),
            "regime_score": forecast.get(
                "regime_score"
            ),
            "risk_state": forecast.get("risk_state"),
            "risk_state_score": forecast.get(
                "risk_state_score"
            ),
            "breadth_score": forecast.get(
                "breadth_score"
            ),
            "setup_score": forecast.get(
                "setup_score"
            ),
            "asymmetry_score": forecast.get(
                "asymmetry_score"
            ),
            "volatility_score": forecast.get(
                "volatility_score"
            ),
            "institutional_sponsorship_score": (
                forecast.get(
                    "institutional_sponsorship_score"
                )
            ),
            "adaptive_institutional_weighting": (
                forecast.get(
                    "adaptive_institutional_weighting"
                )
            ),
            "forecast_regime_trust": forecast.get(
                "forecast_regime_trust"
            ),
            "forecast_regime_trust_actionable": forecast.get(
                "forecast_regime_trust_actionable"
            ),
            "forecast_regime_trust_sample_size": forecast.get(
                "forecast_regime_trust_sample_size"
            ),
            "forecast_regime_bayesian_accuracy_pct": forecast.get(
                "forecast_regime_bayesian_accuracy_pct"
            ),
            "forecast_regime_confidence_adjustment": forecast.get(
                "forecast_regime_confidence_adjustment"
            ),
            "forecast_regime_trust_impact": forecast.get(
                "forecast_regime_trust_impact"
            ),
            "captured": True,
            "deduped": False,
            "status": (
                "FORECAST_OUTCOME_CAPTURED_PENDING_MARKET_RESULT"
            ),
        }

        self.outcome_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.outcome_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

        return record
