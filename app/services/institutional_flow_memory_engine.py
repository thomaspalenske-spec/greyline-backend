import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from threading import Lock


class InstitutionalFlowMemoryEngine:
    HISTORY_PATH = Path(
        "app/data/runtime/institutional_flow_history.jsonl"
    )

    _lock = Lock()

    @staticmethod
    def _float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _event_id(parts):
        raw = "|".join(
            str(part or "")
            for part in parts
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]

    def _read_existing_ids(self):
        if not self.HISTORY_PATH.exists():
            return set()

        ids = set()

        for line in self.HISTORY_PATH.read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue

            event_id = row.get("event_id")

            if event_id:
                ids.add(str(event_id))

        return ids

    def normalize_options_flow(
        self,
        rows,
        symbol=None,
    ):
        normalized = []

        for row in rows or []:
            if not isinstance(row, dict):
                continue

            if row.get("canceled") is True:
                continue

            ticker = str(
                row.get("underlying_symbol")
                or symbol
                or ""
            ).upper().strip()

            if not ticker:
                continue

            executed_at = row.get("executed_at")
            option_type = str(
                row.get("option_type") or ""
            ).upper()

            tags = [
                str(tag).lower()
                for tag in (
                    row.get("tags") or []
                )
            ]

            premium = self._float(
                row.get("premium")
            )

            if "bullish" in tags:
                direction = "BULLISH"
            elif "bearish" in tags:
                direction = "BEARISH"
            elif "ask_side" in tags:
                direction = (
                    "BULLISH"
                    if option_type == "CALL"
                    else "BEARISH"
                )
            elif "bid_side" in tags:
                direction = (
                    "BEARISH"
                    if option_type == "CALL"
                    else "BULLISH"
                )
            else:
                direction = "NEUTRAL"

            provider_id = (
                row.get("id")
                or row.get("flow_alert_id")
            )

            event_id = self._event_id([
                "UNUSUAL_WHALES",
                "OPTIONS_FLOW",
                provider_id,
                ticker,
                row.get("option_chain_id"),
                executed_at,
                row.get("price"),
                row.get("size"),
                premium,
            ])

            normalized.append({
                "event_id": event_id,
                "provider": "UNUSUAL_WHALES",
                "event_type": "OPTIONS_FLOW",
                "symbol": ticker,
                "executed_at": executed_at,
                "captured_at": (
                    datetime.utcnow().isoformat()
                ),
                "direction": direction,
                "option_type": option_type,
                "expiry": row.get("expiry"),
                "strike": self._float(
                    row.get("strike")
                ),
                "price": self._float(
                    row.get("price")
                ),
                "premium": premium,
                "size": self._int(
                    row.get("size")
                ),
                "volume": self._int(
                    row.get("volume")
                ),
                "open_interest": self._int(
                    row.get("open_interest")
                ),
                "underlying_price": self._float(
                    row.get("underlying_price")
                ),
                "implied_volatility": self._float(
                    row.get(
                        "implied_volatility"
                    )
                ),
                "delta": self._float(
                    row.get("delta")
                ),
                "gamma": self._float(
                    row.get("gamma")
                ),
                "theta": self._float(
                    row.get("theta")
                ),
                "vega": self._float(
                    row.get("vega")
                ),
                "nbbo_bid": self._float(
                    row.get("nbbo_bid")
                ),
                "nbbo_ask": self._float(
                    row.get("nbbo_ask")
                ),
                "exchange": row.get("exchange"),
                "tags": tags,
                "option_chain_id": row.get(
                    "option_chain_id"
                ),
                "provider_event_id": provider_id,
            })

        return normalized

    def normalize_dark_pool(
        self,
        payload,
        symbol=None,
    ):
        if isinstance(payload, dict):
            rows = payload.get("data") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []

        normalized = []

        for row in rows:
            if not isinstance(row, dict):
                continue

            if row.get("canceled") is True:
                continue

            ticker = str(
                row.get("ticker")
                or symbol
                or ""
            ).upper().strip()

            if not ticker:
                continue

            price = self._float(
                row.get("price")
            )

            bid = self._float(
                row.get("nbbo_bid")
            )

            ask = self._float(
                row.get("nbbo_ask")
            )

            premium = self._float(
                row.get("premium")
            )

            if bid and ask:
                midpoint = (
                    bid + ask
                ) / 2

                if price > midpoint:
                    direction = "BULLISH"
                elif price < midpoint:
                    direction = "BEARISH"
                else:
                    direction = "NEUTRAL"
            else:
                direction = "NEUTRAL"

            executed_at = (
                row.get("trf_executed_at")
                or row.get("executed_at")
            )

            provider_id = row.get(
                "tracking_id"
            )

            event_id = self._event_id([
                "UNUSUAL_WHALES",
                "DARK_POOL",
                provider_id,
                ticker,
                executed_at,
                price,
                row.get("size"),
                premium,
            ])

            normalized.append({
                "event_id": event_id,
                "provider": "UNUSUAL_WHALES",
                "event_type": "DARK_POOL",
                "symbol": ticker,
                "executed_at": executed_at,
                "captured_at": (
                    datetime.utcnow().isoformat()
                ),
                "direction": direction,
                "price": price,
                "premium": premium,
                "size": self._int(
                    row.get("size")
                ),
                "volume": self._int(
                    row.get("volume")
                ),
                "nbbo_bid": bid,
                "nbbo_ask": ask,
                "nbbo_bid_quantity": self._int(
                    row.get(
                        "nbbo_bid_quantity"
                    )
                ),
                "nbbo_ask_quantity": self._int(
                    row.get(
                        "nbbo_ask_quantity"
                    )
                ),
                "market_center": row.get(
                    "market_center"
                ),
                "extended_hours_code": row.get(
                    "ext_hour_sold_codes"
                ),
                "sale_condition_codes": row.get(
                    "sale_cond_codes"
                ),
                "provider_event_id": provider_id,
            })

        return normalized

    def append(self, events):
        events = [
            event
            for event in events or []
            if isinstance(event, dict)
            and event.get("event_id")
        ]

        if not events:
            return {
                "records_received": 0,
                "records_appended": 0,
                "records_deduped": 0,
                "status": "FLOW_MEMORY_READY",
            }

        self.HISTORY_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._lock:
            existing_ids = (
                self._read_existing_ids()
            )

            new_events = []

            for event in events:
                event_id = str(
                    event.get("event_id")
                )

                if event_id in existing_ids:
                    continue

                existing_ids.add(event_id)
                new_events.append(event)

            if new_events:
                with self.HISTORY_PATH.open(
                    "a"
                ) as f:
                    for event in new_events:
                        f.write(
                            json.dumps(
                                event,
                                sort_keys=True,
                            )
                            + "\n"
                        )

        return {
            "records_received": len(events),
            "records_appended": len(
                new_events
            ),
            "records_deduped": (
                len(events)
                - len(new_events)
            ),
            "status": "FLOW_MEMORY_READY",
        }

    def capture_options_flow(
        self,
        rows,
        symbol=None,
    ):
        return self.append(
            self.normalize_options_flow(
                rows,
                symbol=symbol,
            )
        )

    def capture_dark_pool(
        self,
        payload,
        symbol=None,
    ):
        return self.append(
            self.normalize_dark_pool(
                payload,
                symbol=symbol,
            )
        )

    def summarize(self, symbol=None):
        if not self.HISTORY_PATH.exists():
            return {
                "sample_size": 0,
                "symbols": {},
                "event_types": {},
                "premium_by_direction": {},
                "status": "FLOW_MEMORY_READY",
            }

        symbol = (
            str(symbol).upper().strip()
            if symbol
            else None
        )

        symbols = Counter()
        event_types = Counter()
        premium_by_direction = defaultdict(
            float
        )

        total = 0

        for line in self.HISTORY_PATH.read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue

            ticker = str(
                row.get("symbol") or ""
            ).upper()

            if symbol and ticker != symbol:
                continue

            total += 1
            symbols[ticker] += 1
            event_types[
                row.get("event_type")
                or "UNKNOWN"
            ] += 1

            direction = (
                row.get("direction")
                or "UNKNOWN"
            )

            premium_by_direction[
                direction
            ] += self._float(
                row.get("premium")
            )

        return {
            "sample_size": total,
            "symbols": dict(symbols),
            "event_types": dict(event_types),
            "premium_by_direction": {
                key: round(value, 2)
                for key, value
                in premium_by_direction.items()
            },
            "status": "FLOW_MEMORY_READY",
        }
