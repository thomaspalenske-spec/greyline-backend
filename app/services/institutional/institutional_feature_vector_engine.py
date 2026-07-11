
from datetime import datetime


class InstitutionalFeatureVectorEngine:

    SCHEMA_VERSION = 1

    def build(
        self,
        snapshot,
    ):

        snapshot = snapshot or {}

        providers = snapshot.get(
            "providers",
            {},
        )

        uw = providers.get(
            "UNUSUAL_WHALES",
            {},
        )

        ts = providers.get(
            "TRADESTATION",
            {},
        )

        vector = {
            "timestamp":
                datetime.utcnow().isoformat(),

            "schema_version":
                self.SCHEMA_VERSION,

            "symbol":
                snapshot.get("symbol"),

            "provider_health":
                snapshot.get(
                    "provider_health"
                ),

            "requested_provider_count":
                snapshot.get(
                    "requested_provider_count",
                    0,
                ),

            "connected_provider_count":
                snapshot.get(
                    "connected_provider_count",
                    0,
                ),

            "degraded_provider_count":
                snapshot.get(
                    "degraded_provider_count",
                    0,
                ),

            "uw_available_signal_count":
                len(
                    uw.get(
                        "available_signals",
                        []
                    )
                ),

            "uw_unavailable_signal_count":
                len(
                    uw.get(
                        "unavailable_signals",
                        []
                    )
                ),

            "uw_degraded_signal_count":
                len(
                    uw.get(
                        "degraded_signals",
                        []
                    )
                ),

            "tradestation_component_count":
                len(
                    ts.get(
                        "available_components",
                        []
                    )
                ),

            "execution_impact":
                "OBSERVATION_ONLY",

            "status":
                "INSTITUTIONAL_FEATURE_VECTOR_READY",
        }

        return vector
