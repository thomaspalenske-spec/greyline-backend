from datetime import datetime
from os import getenv


class LiveOrderSafetyError(RuntimeError):
    """Raised when a live (real-money) order is attempted without full authorization."""


# Known TradeStation hosts. Sandbox is checked first because sim-api.tradestation.com
# also ends with ".tradestation.com".
def broker_base_url():
    # Same variable the live broker engines read. Fails safe to the sandbox host.
    return getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")


def classify_broker_endpoint(base_url):
    host = (base_url or "").split("//")[-1].split("/")[0].lower().strip()
    if not host:
        return "UNKNOWN"
    if "sim" in host:
        return "SANDBOX"
    if host == "api.tradestation.com" or host.endswith(".tradestation.com"):
        return "PRODUCTION"
    return "UNKNOWN"


class LiveOrderSafetyGuard:
    """
    Fail-closed gate that MUST be called before any code path that places a real
    (live) broker order. It requires, all at once:

      1. GREYLINE_LIVE_TRADING_ENABLED = true          (live master switch)
      2. GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED = true   (live order placement)
      3. Broker endpoint is SANDBOX, OR it is PRODUCTION and the operator has
         explicitly set GREYLINE_LIVE_PRODUCTION_CONFIRMED = true.

    The whole point of (3): TRADESTATION_SANDBOX_URL may hold a PRODUCTION host, so
    real orders must never fire against production without a conscious acknowledgement.
    """

    def authorize(self):
        base_url = broker_base_url()
        endpoint_env = classify_broker_endpoint(base_url)

        live_trading_enabled = getenv("GREYLINE_LIVE_TRADING_ENABLED", "false").lower() == "true"
        order_placement_allowed = getenv("GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED", "false").lower() == "true"
        production_confirmed = getenv("GREYLINE_LIVE_PRODUCTION_CONFIRMED", "false").lower() == "true"

        blockers = []
        if not live_trading_enabled:
            blockers.append("GREYLINE_LIVE_TRADING_ENABLED is not true")
        if not order_placement_allowed:
            blockers.append("GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED is not true")
        if endpoint_env == "PRODUCTION" and not production_confirmed:
            blockers.append(
                "Broker endpoint is PRODUCTION but GREYLINE_LIVE_PRODUCTION_CONFIRMED is not true"
            )
        if endpoint_env == "UNKNOWN":
            blockers.append(f"Broker endpoint host is unrecognized: {base_url}")

        authorized = len(blockers) == 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "source": "LIVE_ORDER_SAFETY_GUARD",
            "authorized": authorized,
            "endpoint_env": endpoint_env,
            "broker_base_url": base_url,
            "live_trading_enabled": live_trading_enabled,
            "order_placement_allowed": order_placement_allowed,
            "production_confirmed": production_confirmed,
            "blockers": blockers,
            "reason": "Live order placement authorized." if authorized else "; ".join(blockers),
            "status": "LIVE_ORDER_SAFETY_AUTHORIZED" if authorized else "LIVE_ORDER_SAFETY_BLOCKED",
        }

    def assert_safe_to_place_live_order(self):
        """Call this immediately before any real broker-order POST. Raises if not safe."""
        result = self.authorize()
        if not result["authorized"]:
            raise LiveOrderSafetyError(result["reason"])
        return result
