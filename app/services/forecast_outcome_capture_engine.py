from datetime import datetime
import hashlib
import json
import threading
from pathlib import Path

from app.services.tradestation_quote_live_engine import (
    TradeStationQuoteLiveEngine,
)


class ForecastOutcomeCaptureEngine:
    _capture_lock = threading.Lock()

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

    def _read_existing_ids(self, limit=1000):
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

    def _read_existing_dedupe_keys(self, limit=1000):
        if not self.outcome_path.exists():
            return set()

        keys = set()

        for line in self.outcome_path.read_text().splitlines()[-limit:]:
            try:
                row = json.loads(line)
            except Exception:
                continue

            key = row.get("capture_dedupe_key")

            if key:
                keys.add(str(key))
                continue

            timestamp = (
                row.get("forecast_timestamp")
                or row.get("timestamp")
            )

            try:
                row_time = datetime.fromisoformat(
                    str(timestamp).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except Exception:
                continue

            derived_forecast = {
                "symbol": row.get("symbol"),
                "directional_bias": (
                    row.get("predicted_direction")
                    or row.get("directional_bias")
                ),
                "option_type": row.get("option_type"),
                "result": row.get("result"),
                "regime": row.get("regime"),
                "composite_score": (
                    row.get("predicted_score")
                    or row.get("composite_score")
                    or row.get("score")
                ),
            }

            keys.add(
                self._capture_dedupe_key(
                    derived_forecast,
                    now=row_time,
                )
            )

        return keys

    @staticmethod
    def _capture_dedupe_key(forecast, now=None):
        forecast = forecast or {}
        now = now or datetime.utcnow()

        symbol = str(
            forecast.get("symbol") or "UNKNOWN"
        ).upper()

        direction = str(
            forecast.get("directional_bias")
            or forecast.get("predicted_direction")
            or "UNKNOWN"
        ).upper()

        option_type = str(
            forecast.get("option_type") or "UNKNOWN"
        ).upper()

        result = str(
            forecast.get("result") or "UNKNOWN"
        ).upper()

        regime = str(
            forecast.get("regime") or "UNKNOWN"
        ).upper()

        try:
            score = round(
                float(
                    forecast.get(
                        "composite_score",
                        forecast.get("score"),
                    )
                    or 0.0
                )
            )
        except Exception:
            score = 0

        minute_bucket = (
            now.minute // 15
        ) * 15

        bucket = now.replace(
            minute=minute_bucket,
            second=0,
            microsecond=0,
        ).isoformat()

        raw = "|".join([
            symbol,
            direction,
            option_type,
            result,
            regime,
            str(score),
            bucket,
        ])

        digest = hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:20]

        return (
            f"{symbol}-{direction}-"
            f"{bucket}-{digest}"
        )

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
        capture_dedupe_key = (
            self._capture_dedupe_key(forecast)
        )

        price_info = self._last_price(symbol)

        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "forecast_id": forecast_id,
            "capture_dedupe_key": capture_dedupe_key,
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
            "regime_calibration": forecast.get(
                "regime_calibration"
            ),
            "regime_calibration_state": forecast.get(
                "regime_calibration_state"
            ),
            "regime_calibration_actionable": forecast.get(
                "regime_calibration_actionable"
            ),
            "regime_position_multiplier": forecast.get(
                "regime_position_multiplier"
            ),
            "regime_execution_allowed": forecast.get(
                "regime_execution_allowed"
            ),
            "regime_confidence_adjustment": (
                (
                    forecast.get("regime_calibration")
                    or {}
                ).get("confidence_adjustment")
            ),
            "regime_composite_adjustment": forecast.get(
                "regime_composite_adjustment"
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

        # The dedupe check and append must occur under the same
        # process-wide lock. Otherwise two concurrent scheduler or
        # manual cycles can both pass the check before either writes.
        with self._capture_lock:
            existing_ids = self._read_existing_ids()
            existing_dedupe_keys = (
                self._read_existing_dedupe_keys()
            )

            if (
                forecast_id in existing_ids
                or capture_dedupe_key
                in existing_dedupe_keys
            ):
                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "forecast_id": forecast_id,
                    "capture_dedupe_key": (
                        capture_dedupe_key
                    ),
                    "symbol": symbol,
                    "captured": False,
                    "deduped": True,
                    "dedupe_reason": (
                        "FORECAST_ID_DUPLICATE"
                        if forecast_id in existing_ids
                        else "NEAR_IDENTICAL_FORECAST_15M"
                    ),
                    "status": (
                        "FORECAST_OUTCOME_CAPTURE_DEDUPED"
                    ),
                }

            with self.outcome_path.open("a") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()

        return record
