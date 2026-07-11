from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from app.services.data_providers.unusual_whales_provider import (
    UnusualWhalesProvider,
)


class InstitutionalSignalCollectionEngine:
    """
    Central observation-only institutional signal collector.

    Safety:
    - Live provider collection is opt-in.
    - No scoring or execution influence.
    - Provider failures are isolated.
    - Unusual Whales request budgeting and caching remain enforced
      by UnusualWhalesProvider.
    """

    PROVIDERS = (
        "UNUSUAL_WHALES",
        "TRADESTATION",
    )

    def __init__(self):
        try:
            self.unusual_whales = (
                UnusualWhalesProvider()
            )
        except Exception:
            self.unusual_whales = None

    @staticmethod
    def _symbol(value: str) -> str:
        symbol = (
            value
            or ""
        ).upper().strip()

        if not symbol:
            raise ValueError(
                "symbol is required"
            )

        return symbol

    @staticmethod
    def _signal_names(
        signal_names: Optional[
            Iterable[str]
        ],
    ):
        if signal_names is None:
            return None

        return [
            str(name).strip()
            for name in signal_names
            if str(name).strip()
        ]

    def unusual_whales_registry(
        self,
    ) -> Dict[str, Any]:
        signals = sorted(
            UnusualWhalesProvider
            .OBSERVATION_ONLY_ENDPOINTS
        )

        return {
            "provider": "UNUSUAL_WHALES",
            "registered_signal_count": len(
                signals
            ),
            "registered_signals": signals,
            "live_collection_enabled": False,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "UNUSUAL_WHALES_SIGNAL_"
                "REGISTRY_READY"
            ),
        }

    def _collect_unusual_whales(
        self,
        symbol: str,
        signal_names=None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        if self.unusual_whales is None:
            return {
                "connected": False,
                "requested": True,
                "status": (
                    "UNUSUAL_WHALES_PROVIDER_"
                    "UNAVAILABLE"
                ),
                "signals": {},
            }

        selected = self._signal_names(
            signal_names
        )

        try:
            bundle = (
                self.unusual_whales
                .observation_bundle(
                    symbol,
                    signal_names=selected,
                    force_refresh=force_refresh,
                )
            )
        except Exception as exc:
            return {
                "connected": False,
                "requested": True,
                "error": repr(exc),
                "signals": {},
                "status": (
                    "UNUSUAL_WHALES_COLLECTION_"
                    "DEGRADED"
                ),
            }

        return {
            "connected": bool(
                bundle.get(
                    "available_signal_count"
                )
            ),
            "requested": True,
            "requested_signal_count": (
                bundle.get(
                    "requested_signal_count"
                )
            ),
            "available_signal_count": (
                bundle.get(
                    "available_signal_count"
                )
            ),
            "unavailable_signal_count": (
                bundle.get(
                    "unavailable_signal_count"
                )
            ),
            "degraded_signal_count": (
                bundle.get(
                    "degraded_signal_count"
                )
            ),
            "available_signals": (
                bundle.get(
                    "available_signals"
                )
                or []
            ),
            "unavailable_signals": (
                bundle.get(
                    "unavailable_signals"
                )
                or []
            ),
            "degraded_signals": (
                bundle.get(
                    "degraded_signals"
                )
                or []
            ),
            "signals": (
                bundle.get("signals")
                or {}
            ),
            "status": bundle.get(
                "status"
            ),
        }

    def collect(
        self,
        symbol: str,
        collect_unusual_whales: bool = False,
        unusual_whales_signals=None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        symbol = self._symbol(symbol)

        if collect_unusual_whales:
            unusual_whales = (
                self._collect_unusual_whales(
                    symbol,
                    signal_names=(
                        unusual_whales_signals
                    ),
                    force_refresh=force_refresh,
                )
            )
        else:
            registry = (
                self.unusual_whales_registry()
            )

            unusual_whales = {
                "connected": bool(
                    self.unusual_whales
                ),
                "requested": False,
                "registered_signal_count": (
                    registry.get(
                        "registered_signal_count"
                    )
                ),
                "registered_signals": (
                    registry.get(
                        "registered_signals"
                    )
                ),
                "status": (
                    "UNUSUAL_WHALES_COLLECTION_"
                    "NOT_REQUESTED"
                ),
                "signals": {},
            }

        tradestation = {
            "connected": False,
            "requested": False,
            "status": (
                "TRADESTATION_COLLECTION_"
                "NOT_IMPLEMENTED"
            ),
            "signals": {},
        }

        provider_results = {
            "UNUSUAL_WHALES": (
                unusual_whales
            ),
            "TRADESTATION": tradestation,
        }

        requested_providers = [
            name
            for name, result
            in provider_results.items()
            if result.get("requested") is True
        ]

        connected_providers = [
            name
            for name, result
            in provider_results.items()
            if (
                result.get("requested") is True
                and result.get("connected") is True
            )
        ]

        degraded_providers = [
            name
            for name, result
            in provider_results.items()
            if "DEGRADED" in str(
                result.get("status") or ""
            )
        ]

        if degraded_providers:
            provider_health = "DEGRADED"
        elif connected_providers:
            provider_health = "CONNECTED"
        elif requested_providers:
            provider_health = "UNAVAILABLE"
        else:
            provider_health = "NOT_COLLECTED"

        return {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "symbol": symbol,
            "providers": provider_results,
            "provider_count": len(
                self.PROVIDERS
            ),
            "requested_provider_count": len(
                requested_providers
            ),
            "connected_provider_count": len(
                connected_providers
            ),
            "degraded_provider_count": len(
                degraded_providers
            ),
            "provider_health": provider_health,
            "execution_impact": (
                "OBSERVATION_ONLY"
            ),
            "status": (
                "INSTITUTIONAL_SIGNAL_"
                "COLLECTION_READY"
            ),
        }
