import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.live_order_safety_guard_engine import (
    LiveOrderSafetyGuard,
    LiveOrderSafetyError,
    classify_broker_endpoint,
)

GUARD = "app.services.live_order_safety_guard_engine"


def _authorize(env):
    def fake_getenv(key, default=None):
        return env.get(key, default)

    with patch(f"{GUARD}.getenv", side_effect=fake_getenv):
        return LiveOrderSafetyGuard().authorize()


# ---- endpoint classification ----
def test_classify_sandbox_and_production():
    assert classify_broker_endpoint("https://sim-api.tradestation.com") == "SANDBOX"
    assert classify_broker_endpoint("https://api.tradestation.com") == "PRODUCTION"
    assert classify_broker_endpoint("https://example.com") == "UNKNOWN"
    assert classify_broker_endpoint("") == "UNKNOWN"


# ---- the core guarantee: production requires explicit confirmation ----
def test_production_blocked_without_confirmation():
    result = _authorize({
        "TRADESTATION_SANDBOX_URL": "https://api.tradestation.com",
        "GREYLINE_LIVE_TRADING_ENABLED": "true",
        "GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED": "true",
        # GREYLINE_LIVE_PRODUCTION_CONFIRMED not set
    })
    assert result["authorized"] is False
    assert result["endpoint_env"] == "PRODUCTION"
    assert any("PRODUCTION" in b for b in result["blockers"])


def test_production_authorized_with_confirmation():
    result = _authorize({
        "TRADESTATION_SANDBOX_URL": "https://api.tradestation.com",
        "GREYLINE_LIVE_TRADING_ENABLED": "true",
        "GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED": "true",
        "GREYLINE_LIVE_PRODUCTION_CONFIRMED": "true",
    })
    assert result["authorized"] is True


def test_sandbox_does_not_require_production_confirmation():
    result = _authorize({
        "TRADESTATION_SANDBOX_URL": "https://sim-api.tradestation.com",
        "GREYLINE_LIVE_TRADING_ENABLED": "true",
        "GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED": "true",
    })
    assert result["authorized"] is True
    assert result["endpoint_env"] == "SANDBOX"


# ---- fail-safe: everything off ----
def test_blocked_when_live_flags_disabled():
    result = _authorize({"TRADESTATION_SANDBOX_URL": "https://sim-api.tradestation.com"})
    assert result["authorized"] is False
    assert len(result["blockers"]) >= 2


def test_unset_url_defaults_to_sandbox_and_is_not_production():
    # No TRADESTATION_SANDBOX_URL -> default sandbox host, never production.
    result = _authorize({
        "GREYLINE_LIVE_TRADING_ENABLED": "true",
        "GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED": "true",
    })
    assert result["endpoint_env"] == "SANDBOX"
    assert result["authorized"] is True


# ---- assert helper raises ----
def test_assert_raises_when_not_authorized():
    def fake_getenv(key, default=None):
        return {"TRADESTATION_SANDBOX_URL": "https://api.tradestation.com"}.get(key, default)

    with patch(f"{GUARD}.getenv", side_effect=fake_getenv):
        with pytest.raises(LiveOrderSafetyError):
            LiveOrderSafetyGuard().assert_safe_to_place_live_order()


def test_assert_returns_result_when_authorized():
    def fake_getenv(key, default=None):
        return {
            "TRADESTATION_SANDBOX_URL": "https://sim-api.tradestation.com",
            "GREYLINE_LIVE_TRADING_ENABLED": "true",
            "GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED": "true",
        }.get(key, default)

    with patch(f"{GUARD}.getenv", side_effect=fake_getenv):
        result = LiveOrderSafetyGuard().assert_safe_to_place_live_order()
    assert result["authorized"] is True


# ---- the live authority gate now enforces the production check too ----
def test_authority_gate_locks_on_unconfirmed_production():
    GATE = "app.services.live_trade_authority_gate_engine"
    import app.services.live_trade_authority_gate_engine as gate_mod

    def fake_getenv(key, default=None):
        return {
            "GREYLINE_LIVE_EXECUTION_ENABLED": "true",
            "GREYLINE_ORDER_PLACEMENT_ALLOWED": "true",
            "GREYLINE_KILL_SWITCH_STATE": "ARMED",
            "TRADESTATION_SANDBOX_URL": "https://api.tradestation.com",
            # production not confirmed
        }.get(key, default)

    with patch(f"{GATE}.getenv", side_effect=fake_getenv), \
         patch(f"{GATE}.load_dotenv"), \
         patch(f"{GATE}.broker_base_url", return_value="https://api.tradestation.com"), \
         patch(f"{GATE}.ImmutableAuditLedgerEngine"):
        result = gate_mod.LiveTradeAuthorityGateEngine().evaluate()

    assert result["endpoint_env"] == "PRODUCTION"
    assert result["endpoint_safe"] is False
    assert result["authority_armed"] is False
