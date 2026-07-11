import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


class InstitutionalFlowMemoryAnalyticsEngine:
    HISTORY_PATH = Path(
        "app/data/runtime/institutional_flow_history.jsonl"
    )

    WINDOWS = {
        "1d": 1,
        "5d": 5,
        "20d": 20,
    }

    @staticmethod
    def _float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None

        try:
            dt = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except Exception:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    def _read_events(self, symbol):
        if not self.HISTORY_PATH.exists():
            return []

        symbol = str(
            symbol or ""
        ).upper().strip()

        events = []

        for line in self.HISTORY_PATH.read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue

            if str(
                row.get("symbol") or ""
            ).upper() != symbol:
                continue

            event_time = self._parse_datetime(
                row.get("executed_at")
                or row.get("captured_at")
            )

            if event_time is None:
                continue

            events.append({
                **row,
                "_event_time": event_time,
            })

        events.sort(
            key=lambda row: row["_event_time"]
        )

        return events

    def _window_summary(
        self,
        events,
        start_time,
        end_time,
    ):
        rows = [
            row
            for row in events
            if (
                start_time
                <= row["_event_time"]
                < end_time
            )
        ]

        premium = defaultdict(float)
        counts = defaultdict(int)
        event_types = defaultdict(int)
        active_dates = set()

        for row in rows:
            active_dates.add(
                row["_event_time"].date().isoformat()
            )
            direction = str(
                row.get("direction")
                or "NEUTRAL"
            ).upper()

            premium[direction] += self._float(
                row.get("premium")
            )

            counts[direction] += 1

            event_types[
                str(
                    row.get("event_type")
                    or "UNKNOWN"
                )
            ] += 1

        bullish = premium["BULLISH"]
        bearish = premium["BEARISH"]
        neutral = premium["NEUTRAL"]

        directional_total = (
            bullish + bearish
        )

        net_premium = round(
            bullish - bearish,
            2,
        )

        imbalance_pct = (
            round(
                (
                    net_premium
                    / directional_total
                ) * 100,
                2,
            )
            if directional_total > 0
            else 0.0
        )

        if imbalance_pct >= 15:
            direction = "BULLISH"
        elif imbalance_pct <= -15:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = round(
            min(
                100.0,
                abs(imbalance_pct),
            ),
            2,
        )

        return {
            "sample_size": len(rows),
            "active_trading_day_count": len(
                active_dates
            ),
            "active_trading_days": sorted(
                active_dates
            ),
            "bullish_event_count": counts[
                "BULLISH"
            ],
            "bearish_event_count": counts[
                "BEARISH"
            ],
            "neutral_event_count": counts[
                "NEUTRAL"
            ],
            "event_types": dict(
                event_types
            ),
            "bullish_premium": round(
                bullish,
                2,
            ),
            "bearish_premium": round(
                bearish,
                2,
            ),
            "neutral_premium": round(
                neutral,
                2,
            ),
            "directional_premium": round(
                directional_total,
                2,
            ),
            "net_premium": net_premium,
            "premium_imbalance_pct": (
                imbalance_pct
            ),
            "direction": direction,
            "confidence": confidence,
        }

    @staticmethod
    def _persistence(windows):
        directions = [
            windows.get(name, {}).get(
                "direction"
            )
            for name in [
                "1d",
                "5d",
                "20d",
            ]
        ]

        distinct_dates = set()

        for window in windows.values():
            distinct_dates.update(
                window.get(
                    "active_trading_days"
                )
                or []
            )

        non_neutral = [
            direction
            for direction in directions
            if direction in [
                "BULLISH",
                "BEARISH",
            ]
        ]

        if len(distinct_dates) < 2:
            return {
                "direction": "UNCONFIRMED",
                "window_count": 0,
                "distinct_trading_day_count": len(
                    distinct_dates
                ),
                "state": "INSUFFICIENT_TRADING_DAYS",
            }

        if len(non_neutral) < 2:
            return {
                "direction": "UNCONFIRMED",
                "window_count": len(
                    non_neutral
                ),
                "distinct_trading_day_count": len(
                    distinct_dates
                ),
                "state": "INSUFFICIENT_HISTORY",
            }

        bullish_count = non_neutral.count(
            "BULLISH"
        )

        bearish_count = non_neutral.count(
            "BEARISH"
        )

        if bullish_count > bearish_count:
            direction = "BULLISH"
            count = bullish_count
        elif bearish_count > bullish_count:
            direction = "BEARISH"
            count = bearish_count
        else:
            direction = "MIXED"
            count = bullish_count

        if count == 3:
            state = "STRONG_PERSISTENCE"
        elif count == 2:
            state = "CONFIRMED_PERSISTENCE"
        else:
            state = "MIXED"

        return {
            "direction": direction,
            "window_count": count,
            "distinct_trading_day_count": len(
                distinct_dates
            ),
            "state": state,
        }

    @staticmethod
    def _acceleration(windows):
        one_day = windows.get(
            "1d",
            {}
        )

        five_day = windows.get(
            "5d",
            {}
        )

        one_day_days = max(
            1,
            int(
                one_day.get(
                    "active_trading_day_count"
                )
                or 0
            ),
        )

        five_day_days = int(
            five_day.get(
                "active_trading_day_count"
            )
            or 0
        )

        one_day_rate = (
            float(
                one_day.get(
                    "net_premium"
                )
                or 0.0
            )
            / one_day_days
        )

        five_day_rate = (
            float(
                five_day.get(
                    "net_premium"
                )
                or 0.0
            )
            / five_day_days
            if five_day_days > 0
            else 0.0
        )

        enough_history = (
            five_day_days >= 2
        )

        acceleration = (
            round(
                one_day_rate
                - five_day_rate,
                2,
            )
            if enough_history
            else 0.0
        )

        if not enough_history:
            state = "INSUFFICIENT_TRADING_DAYS"
        elif acceleration > 250000:
            state = (
                "BULLISH_ACCELERATION"
            )
        elif acceleration < -250000:
            state = (
                "BEARISH_ACCELERATION"
            )
        else:
            state = "STABLE"

        return {
            "one_day_net_premium": round(
                one_day_rate,
                2,
            ),
            "five_day_daily_average": round(
                five_day_rate,
                2,
            ),
            "acceleration": acceleration,
            "active_trading_day_count": (
                five_day_days
            ),
            "state": state,
        }

    def evaluate(
        self,
        symbol,
        as_of=None,
    ):
        symbol = str(
            symbol or ""
        ).upper().strip()

        as_of = as_of or datetime.now(
            timezone.utc
        )

        if as_of.tzinfo is None:
            as_of = as_of.replace(
                tzinfo=timezone.utc
            )

        events = self._read_events(
            symbol
        )

        windows = {}

        for name, days in self.WINDOWS.items():
            windows[name] = (
                self._window_summary(
                    events,
                    as_of - timedelta(
                        days=days
                    ),
                    as_of,
                )
            )

        persistence = self._persistence(
            windows
        )

        acceleration = self._acceleration(
            windows
        )

        one_day = windows["1d"]
        five_day = windows["5d"]
        twenty_day = windows["20d"]

        base_score = 50.0

        base_score += (
            one_day[
                "premium_imbalance_pct"
            ]
            * 0.20
        )

        base_score += (
            five_day[
                "premium_imbalance_pct"
            ]
            * 0.20
        )

        base_score += (
            twenty_day[
                "premium_imbalance_pct"
            ]
            * 0.10
        )

        if persistence["direction"] == (
            "BULLISH"
        ):
            base_score += (
                persistence[
                    "window_count"
                ]
                * 5
            )

        elif persistence["direction"] == (
            "BEARISH"
        ):
            base_score -= (
                persistence[
                    "window_count"
                ]
                * 5
            )

        if acceleration["state"] == (
            "BULLISH_ACCELERATION"
        ):
            base_score += 8

        elif acceleration["state"] == (
            "BEARISH_ACCELERATION"
        ):
            base_score -= 8

        conviction_score = round(
            max(
                0.0,
                min(
                    100.0,
                    base_score,
                ),
            ),
            2,
        )

        if conviction_score >= 65:
            conviction_direction = (
                "BULLISH"
            )
        elif conviction_score <= 35:
            conviction_direction = (
                "BEARISH"
            )
        else:
            conviction_direction = (
                "NEUTRAL"
            )

        actionable = bool(
            five_day.get(
                "sample_size",
                0,
            ) >= 20
            and five_day.get(
                "active_trading_day_count",
                0,
            ) >= 2
            and persistence.get(
                "window_count",
                0,
            ) >= 2
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": (
                "InstitutionalFlowMemoryAnalyticsEngine"
            ),
            "symbol": symbol,
            "event_count": len(events),
            "windows": windows,
            "persistence": persistence,
            "acceleration": acceleration,
            "institutional_memory_score": (
                conviction_score
            ),
            "institutional_memory_direction": (
                conviction_direction
            ),
            "actionable": actionable,
            "execution_impact": (
                "INSTITUTIONAL_MEMORY_ACTIVE"
                if actionable
                else "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_FLOW_MEMORY_ANALYTICS_READY"
            ),
        }
