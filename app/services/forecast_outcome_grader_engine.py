from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.price_history_store import PriceHistoryStore
from app.services.time_utils import parse_utc
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.regime_learning_engine import (
    RegimeLearningEngine,
)
from app.services.forecast_quality_learning_engine import (
    ForecastQualityLearningEngine,
)


class ForecastOutcomeGraderEngine:

    MARKET_TZ = ZoneInfo("America/New_York")

    def _market_is_open(self, dt=None):
        dt = dt or datetime.now(timezone.utc)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        market_time = dt.astimezone(
            self.MARKET_TZ
        )

        if market_time.weekday() >= 5:
            return False

        minutes = (
            market_time.hour * 60
            + market_time.minute
        )

        return 570 <= minutes < 960

    def __init__(self):
        self.outcome_path = Path("app/data/forecast_outcomes.jsonl")
        self.graded_path = Path("app/data/forecast_outcome_grades.jsonl")
        self.price_store = PriceHistoryStore()

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
            return parse_utc(value)
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

    def grade_pending(
        self,
        market_prices=None,
        min_age_minutes=60,
        limit=500,
    ):
        market_prices = market_prices or {}
        outcomes = self._read_outcomes()
        graded = []
        price_cache = {}

        records = (
            outcomes[-limit:]
            if limit is not None
            else outcomes
        )

        for record in records:
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
                    "forecast_confidence": record.get(
                        "forecast_confidence"
                    ),
                    "direction_confidence": record.get(
                        "direction_confidence"
                    ),

                    # Preserve regime calibration metadata even while pending.
                    "regime": record.get("regime"),
                    "regime_score": record.get("regime_score"),
                    "forecast_regime_trust": record.get(
                        "forecast_regime_trust"
                    ),
                    "forecast_regime_trust_actionable": record.get(
                        "forecast_regime_trust_actionable"
                    ),
                    "forecast_regime_trust_sample_size": record.get(
                        "forecast_regime_trust_sample_size"
                    ),
                    "forecast_regime_bayesian_accuracy_pct": record.get(
                        "forecast_regime_bayesian_accuracy_pct"
                    ),
                    "forecast_regime_confidence_adjustment": record.get(
                        "forecast_regime_confidence_adjustment"
                    ),
                    "forecast_regime_trust_impact": record.get(
                        "forecast_regime_trust_impact"
                    ),
                    "regime_calibration": record.get(
                        "regime_calibration"
                    ),
                    "regime_calibration_state": record.get(
                        "regime_calibration_state"
                    ),
                    "regime_calibration_actionable": record.get(
                        "regime_calibration_actionable"
                    ),
                    "regime_position_multiplier": record.get(
                        "regime_position_multiplier"
                    ),
                    "regime_execution_allowed": record.get(
                        "regime_execution_allowed"
                    ),
                    "regime_confidence_adjustment": record.get(
                        "regime_confidence_adjustment"
                    ),
                    "regime_composite_adjustment": record.get(
                        "regime_composite_adjustment"
                    ),

                    "risk_state": record.get("risk_state"),
                    "risk_state_score": record.get(
                        "risk_state_score"
                    ),
                    "breadth_score": record.get(
                        "breadth_score"
                    ),
                    "setup_score": record.get("setup_score"),
                    "asymmetry_score": record.get(
                        "asymmetry_score"
                    ),
                    "volatility_score": record.get(
                        "volatility_score"
                    ),
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

            supplied_market_price = (
                symbol in market_prices
            )

            if (
                not supplied_market_price
                and not self._market_is_open()
            ):
                grade_record = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "forecast_id": record.get(
                        "forecast_id"
                    ),
                    "symbol": symbol,
                    "predicted_direction": (
                        predicted_direction
                    ),
                    "predicted_score": predicted_score,
                    "forecast_confidence": record.get(
                        "forecast_confidence"
                    ),
                    "direction_confidence": record.get(
                        "direction_confidence"
                    ),
                    "regime": record.get("regime"),
                    "regime_score": record.get(
                        "regime_score"
                    ),
                    "forecast_regime_trust": record.get(
                        "forecast_regime_trust"
                    ),
                    "forecast_regime_trust_actionable": (
                        record.get(
                            "forecast_regime_trust_actionable"
                        )
                    ),
                    "forecast_regime_trust_sample_size": (
                        record.get(
                            "forecast_regime_trust_sample_size"
                        )
                    ),
                    "forecast_regime_bayesian_accuracy_pct": (
                        record.get(
                            "forecast_regime_bayesian_accuracy_pct"
                        )
                    ),
                    "forecast_regime_confidence_adjustment": (
                        record.get(
                            "forecast_regime_confidence_adjustment"
                        )
                    ),
                    "forecast_regime_trust_impact": (
                        record.get(
                            "forecast_regime_trust_impact"
                        )
                    ),
                    "regime_calibration": record.get(
                        "regime_calibration"
                    ),
                    "regime_calibration_state": record.get(
                        "regime_calibration_state"
                    ),
                    "regime_calibration_actionable": (
                        record.get(
                            "regime_calibration_actionable"
                        )
                    ),
                    "regime_position_multiplier": (
                        record.get(
                            "regime_position_multiplier"
                        )
                    ),
                    "regime_execution_allowed": (
                        record.get(
                            "regime_execution_allowed"
                        )
                    ),
                    "regime_confidence_adjustment": (
                        record.get(
                            "regime_confidence_adjustment"
                        )
                    ),
                    "regime_composite_adjustment": (
                        record.get(
                            "regime_composite_adjustment"
                        )
                    ),
                    "risk_state": record.get(
                        "risk_state"
                    ),
                    "risk_state_score": record.get(
                        "risk_state_score"
                    ),
                    "breadth_score": record.get(
                        "breadth_score"
                    ),
                    "setup_score": record.get(
                        "setup_score"
                    ),
                    "asymmetry_score": record.get(
                        "asymmetry_score"
                    ),
                    "volatility_score": record.get(
                        "volatility_score"
                    ),
                    "snapshot_price": record.get(
                        "snapshot_price"
                    ),
                    "current_price": None,
                    "return_pct": None,
                    "forecast_grade": (
                        "PENDING_MARKET_SESSION"
                    ),
                    "forecast_correct": None,
                    "quote_status": (
                        "MARKET_CLOSED"
                    ),
                    "quote_trade_time": None,
                    "forecast_age_minutes": (
                        maturity.get(
                            "forecast_age_minutes"
                        )
                    ),
                    "eligible_for_grading": False,
                    "maturity_status": (
                        maturity.get(
                            "maturity_status"
                        )
                    ),
                    "status": (
                        "FORECAST_OUTCOME_GRADE_"
                        "PENDING_MARKET_SESSION"
                    ),
                }

                graded.append(grade_record)
                continue

            if supplied_market_price:
                price_info = {
                    "price": market_prices.get(symbol),
                    "quote_status": "SUPPLIED_MARKET_PRICE",
                    "trade_time": None,
                }
            else:
                # FIXED HORIZON, not the live tape.
                #
                # min_age_minutes was only a lower bound on ELIGIBILITY — nothing sampled
                # the price at forecast_time + horizon. A forecast made four days ago was
                # graded against today's quote, so every A/B/F in this system measured
                # "did the symbol drift my way since some arbitrary past moment" over a
                # ragged, ever-growing window. Look up the price AT the horizon instead,
                # and leave the forecast pending if that price does not exist yet.
                forecast_time = self._parse_dt(
                    record.get("forecast_timestamp") or record.get("timestamp"))
                price_info = {"price": None, "quote_status": "NO_HORIZON_PRICE",
                              "trade_time": None}
                if forecast_time is not None:
                    target = forecast_time + timedelta(minutes=min_age_minutes)
                    hit = self.price_store.price_at(
                        symbol, target.isoformat(),
                        max_tolerance_seconds=int(min_age_minutes * 60 * 0.25),
                        direction="after")
                    if hit:
                        price_info = {"price": hit["price"],
                                      "quote_status": "HORIZON_PRICE",
                                      "trade_time": hit["timestamp"],
                                      "realized_horizon_minutes": round(
                                          min_age_minutes + hit["age_seconds"] / 60, 2)}

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
                directional_return_pct = raw_return_pct
                if predicted_direction == "BEARISH":
                    directional_return_pct = round(-raw_return_pct, 4)

                # `return_pct` is what ForecastQualityLearningEngine reads and calls a win
                # when positive. It was set to the RAW return, so a BEARISH forecast that
                # was RIGHT (price fell 2%) recorded -2% and was bucketed as a loss, while
                # a bearish forecast that was WRONG recorded +2% and counted as a win. The
                # entire bearish book was sign-inverted in average_return_pct, average_win_pct
                # and quality_score — and the same record's forecast_correct field, computed
                # from the directional value below, disagreed with it.
                return_pct = directional_return_pct
                raw_market_return_pct = raw_return_pct

                forecast_correct = directional_return_pct > 0
                forecast_grade = "A" if directional_return_pct >= 1 else "B" if directional_return_pct > 0 else "F"

            grade_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "forecast_id": record.get("forecast_id"),
                "symbol": symbol,
                "predicted_direction": predicted_direction,
                "predicted_score": predicted_score,
                "forecast_confidence": record.get(
                    "forecast_confidence"
                ),
                "direction_confidence": record.get(
                    "direction_confidence"
                ),

                # Preserve market regime and centralized
                # regime-calibration metadata.
                "regime": record.get("regime"),
                "regime_score": record.get("regime_score"),
                "forecast_regime_trust": record.get(
                    "forecast_regime_trust"
                ),
                "forecast_regime_trust_actionable": record.get(
                    "forecast_regime_trust_actionable"
                ),
                "forecast_regime_trust_sample_size": record.get(
                    "forecast_regime_trust_sample_size"
                ),
                "forecast_regime_bayesian_accuracy_pct": record.get(
                    "forecast_regime_bayesian_accuracy_pct"
                ),
                "forecast_regime_confidence_adjustment": record.get(
                    "forecast_regime_confidence_adjustment"
                ),
                "forecast_regime_trust_impact": record.get(
                    "forecast_regime_trust_impact"
                ),
                "regime_calibration": record.get(
                    "regime_calibration"
                ),
                "regime_calibration_state": record.get(
                    "regime_calibration_state"
                ),
                "regime_calibration_actionable": record.get(
                    "regime_calibration_actionable"
                ),
                "regime_position_multiplier": record.get(
                    "regime_position_multiplier"
                ),
                "regime_execution_allowed": record.get(
                    "regime_execution_allowed"
                ),
                "regime_confidence_adjustment": record.get(
                    "regime_confidence_adjustment"
                ),
                "regime_composite_adjustment": record.get(
                    "regime_composite_adjustment"
                ),
                "risk_state": record.get("risk_state"),
                "risk_state_score": record.get(
                    "risk_state_score"
                ),
                "breadth_score": record.get(
                    "breadth_score"
                ),
                "setup_score": record.get("setup_score"),
                "asymmetry_score": record.get(
                    "asymmetry_score"
                ),
                "volatility_score": record.get(
                    "volatility_score"
                ),
                "snapshot_price": (
                    snapshot_price
                    if snapshot_price > 0
                    else None
                ),
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

        existing_grades = {}

        if self.graded_path.exists():
            for line in self.graded_path.read_text().splitlines():
                try:
                    row = json.loads(line)
                except Exception:
                    continue

                forecast_id = row.get("forecast_id")

                if forecast_id:
                    existing_grades[str(forecast_id)] = row

        for row in graded:
            forecast_id = row.get("forecast_id")

            if not forecast_id:
                continue

            key = str(forecast_id)
            existing = existing_grades.get(key)

            existing_completed = bool(
                existing
                and existing.get(
                    "forecast_correct"
                ) is not None
            )

            incoming_pending = (
                row.get("forecast_correct")
                is None
            )

            # A completed grade is FINAL. The guard used to protect a completed grade only
            # from being clobbered by a PENDING one, so a completed grade was replaced by a
            # freshly computed completed grade on every scheduler cycle — a forecast graded
            # at T+1h was silently re-graded at T+2h, T+3h and so on, and the stored verdict
            # was whatever the last cycle happened to say. That is what let each forecast's
            # measurement window grow without bound, and it made the fixed horizon
            # unenforceable no matter how the price was sampled.
            if existing_completed:
                continue

            existing_grades[key] = row

        ordered_grades = list(existing_grades.values())

        ordered_grades.sort(
            key=lambda row: (
                row.get("timestamp") or "",
                row.get("forecast_id") or "",
            )
        )

        self.graded_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.graded_path.open("w") as f:
            for row in ordered_grades:
                f.write(json.dumps(row) + "\n")

        completed_grades = [
            row
            for row in ordered_grades
            if (
                row.get("forecast_correct") is not None
                and row.get("regime_calibration_state")
                and row.get("forecast_regime_trust") is not None
            )
        ]

        try:
            regime_learning = (
                RegimeLearningEngine().evaluate(
                    completed_grades
                )
            )
        except Exception as exc:
            regime_learning = {
                "timestamp": datetime.utcnow().isoformat(),
                "engine": "RegimeLearningEngine",
                "learning": {},
                "error": repr(exc),
                "status": "REGIME_LEARNING_DEGRADED",
            }

        try:
            forecast_quality_learning = (
                ForecastQualityLearningEngine()
                .evaluate(
                    completed_grades
                )
            )
        except Exception as exc:
            forecast_quality_learning = {
                "sample_size": 0,
                "average_return_pct": 0.0,
                "average_absolute_return_pct": 0.0,
                "average_win_pct": 0.0,
                "average_loss_pct": 0.0,
                "quality_score": 0.0,
                "error": repr(exc),
                "status": (
                    "FORECAST_QUALITY_DEGRADED"
                ),
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "ForecastOutcomeGraderEngine",
            "graded_count": len(graded),
            "total_grade_record_count": len(
                ordered_grades
            ),
            "grades": graded,
            "completed_grade_count": len(
                completed_grades
            ),
            "regime_learning": regime_learning,
            "regime_learning_status": (
                regime_learning.get("status")
            ),
            "forecast_quality_learning": (
                forecast_quality_learning
            ),
            "forecast_quality_learning_status": (
                forecast_quality_learning.get(
                    "status"
                )
            ),
            "status": "FORECAST_OUTCOME_GRADER_READY",
        }
