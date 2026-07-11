from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services.tradestation_option_chain_live_engine import (
    TradeStationOptionChainLiveEngine,
)
from app.services.tradestation_quote_live_engine import (
    TradeStationQuoteLiveEngine,
)


class TradeStationObservationProvider:
    """
    Observation-only TradeStation market-data provider.

    Verified live sources:
    - Level I equity quote
    - Listed option expirations
    - Option-chain snapshot

    No scoring, execution, or order placement.
    """

    QUOTE_FIELDS = (
        "Symbol",
        "Open",
        "High",
        "Low",
        "PreviousClose",
        "Close",
        "Last",
        "Bid",
        "BidSize",
        "Ask",
        "AskSize",
        "LastSize",
        "LastVenue",
        "NetChange",
        "NetChangePct",
        "VWAP",
        "Volume",
        "PreviousVolume",
        "DailyOpenInterest",
        "TradeTime",
        "High52Week",
        "High52WeekTimestamp",
        "Low52Week",
        "Low52WeekTimestamp",
        "TickSizeTier",
        "Restrictions",
        "MarketFlags",
    )

    OPTION_FIELDS = (
        "Ask",
        "AskSize",
        "Bid",
        "BidSize",
        "Last",
        "Mid",
        "Open",
        "High",
        "Low",
        "Close",
        "PreviousClose",
        "NetChange",
        "NetChangePct",
        "Volume",
        "DailyOpenInterest",
        "Delta",
        "Gamma",
        "Theta",
        "Vega",
        "Rho",
        "ImpliedVolatility",
        "IntrinsicValue",
        "ExtrinsicValue",
        "TheoreticalValue",
        "TheoreticalValue_IV",
        "StandardDeviation",
        "ProbabilityITM",
        "ProbabilityOTM",
        "ProbabilityBE",
        "ProbabilityITM_IV",
        "ProbabilityOTM_IV",
        "ProbabilityBE_IV",
        "Side",
        "Strikes",
        "Legs",
    )

    def __init__(self):
        self.quote_engine = (
            TradeStationQuoteLiveEngine()
        )
        self.option_engine = (
            TradeStationOptionChainLiveEngine()
        )

    @staticmethod
    def _symbol(symbol: str) -> str:
        value = (
            symbol
            or ""
        ).upper().strip()

        if not value:
            raise ValueError(
                "symbol is required"
            )

        return value

    @staticmethod
    def _select_fields(
        row: Dict[str, Any],
        fields,
    ) -> Dict[str, Any]:
        return {
            field: row.get(field)
            for field in fields
            if field in row
        }

    def quote_snapshot(
        self,
        symbol: str,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        result = self.quote_engine.get_quote(
            symbol
        )

        quotes = (
            (result.get("response_json") or {})
            .get("Quotes")
            or []
        )

        row = (
            quotes[0]
            if quotes
            and isinstance(quotes[0], dict)
            else {}
        )

        quote = self._select_fields(
            row,
            self.QUOTE_FIELDS,
        )

        return {
            "provider": "TRADESTATION",
            "symbol": symbol,
            "available": bool(quote),
            "field_count": len(quote),
            "fields": quote,
            "http_status": result.get(
                "http_status"
            ),
            "cache_hit": result.get(
                "cache_hit"
            ),
            "cache_age_seconds": result.get(
                "cache_age_seconds"
            ),
            "source_status": result.get(
                "status"
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "TRADESTATION_QUOTE_"
                "OBSERVATION_READY"
                if quote
                else
                "TRADESTATION_QUOTE_"
                "OBSERVATION_UNAVAILABLE"
            ),
        }

    def expirations(
        self,
        symbol: str,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        result = (
            self.option_engine
            .get_expirations(symbol)
        )

        expirations = (
            result.get("expirations")
            or []
        )

        return {
            "provider": "TRADESTATION",
            "symbol": symbol,
            "available": bool(expirations),
            "expiration_count": len(
                expirations
            ),
            "expirations": expirations,
            "http_status": result.get(
                "http_status"
            ),
            "source_status": result.get(
                "status"
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "TRADESTATION_EXPIRATION_"
                "OBSERVATION_READY"
                if expirations
                else
                "TRADESTATION_EXPIRATION_"
                "OBSERVATION_UNAVAILABLE"
            ),
        }

    def option_chain_snapshot(
        self,
        symbol: str,
        expiration: Optional[str] = None,
        option_type: str = "All",
        max_contracts: int = 10,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        expiration_source = (
            "SUPPLIED_EXPIRATION"
        )

        if not expiration:
            expiration_result = (
                self.expirations(symbol)
            )

            expirations = (
                expiration_result.get(
                    "expirations"
                )
                or []
            )

            if not expirations:
                return {
                    "provider": "TRADESTATION",
                    "symbol": symbol,
                    "available": False,
                    "expiration": None,
                    "contract_count": 0,
                    "contracts": [],
                    "execution_impact": (
                        "OBSERVATION_ONLY"
                    ),
                    "status": (
                        "TRADESTATION_OPTION_CHAIN_"
                        "EXPIRATION_UNAVAILABLE"
                    ),
                }

            expiration = (
                expirations[0]
                .split("T", 1)[0]
            )

            expiration_source = (
                "DISCOVERED_EXPIRATION"
            )

        result = (
            self.option_engine
            .get_chain_snapshot(
                symbol,
                expiration,
                option_type=option_type,
                max_contracts=max_contracts,
            )
        )

        raw_contracts = (
            result.get("contracts")
            or []
        )

        contracts = [
            self._select_fields(
                row,
                self.OPTION_FIELDS,
            )
            for row in raw_contracts
            if isinstance(row, dict)
        ]

        return {
            "provider": "TRADESTATION",
            "symbol": symbol,
            "available": bool(contracts),
            "expiration": expiration,
            "expiration_source": (
                expiration_source
            ),
            "option_type": option_type,
            "contract_count": len(
                contracts
            ),
            "contracts": contracts,
            "source_status": result.get(
                "status"
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "TRADESTATION_OPTION_CHAIN_"
                "OBSERVATION_READY"
                if contracts
                else
                "TRADESTATION_OPTION_CHAIN_"
                "OBSERVATION_UNAVAILABLE"
            ),
        }

    def observation_bundle(
        self,
        symbol: str,
        include_option_chain: bool = False,
        expiration: Optional[str] = None,
        option_type: str = "All",
        max_contracts: int = 10,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        quote = self.quote_snapshot(
            symbol
        )

        expirations = self.expirations(
            symbol
        )

        if include_option_chain:
            option_chain = (
                self.option_chain_snapshot(
                    symbol,
                    expiration=expiration,
                    option_type=option_type,
                    max_contracts=max_contracts,
                )
            )
        else:
            option_chain = {
                "provider": "TRADESTATION",
                "symbol": symbol,
                "available": False,
                "requested": False,
                "execution_impact": (
                    "OBSERVATION_ONLY"
                ),
                "status": (
                    "TRADESTATION_OPTION_CHAIN_"
                    "NOT_REQUESTED"
                ),
            }

        available_components = [
            name
            for name, value in {
                "quote": quote,
                "expirations": expirations,
                "option_chain": option_chain,
            }.items()
            if value.get("available") is True
        ]

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "provider": "TRADESTATION",
            "symbol": symbol,
            "quote": quote,
            "expirations": expirations,
            "option_chain": option_chain,
            "available_component_count": len(
                available_components
            ),
            "available_components": (
                available_components
            ),
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "TRADESTATION_OBSERVATION_"
                "BUNDLE_READY"
            ),
        }
