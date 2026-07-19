import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import greyline_live_broker_client_engine as M
from app.services.greyline_live_broker_client_engine import GreyLineLiveBrokerClientEngine
from app.services.live_order_safety_guard_engine import LiveOrderSafetyError


def _no_post(*a, **k):
    raise AssertionError("requests.post was called — a real order escaped the interlock!")


def test_blocks_when_live_switches_off(monkeypatch):
    # Default posture: live trading disabled -> must raise BEFORE any POST.
    for k in ("GREYLINE_LIVE_TRADING_ENABLED", "GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED",
              "GREYLINE_LIVE_PRODUCTION_CONFIRMED"):
        monkeypatch.setenv(k, "false")
    monkeypatch.setattr(M.requests, "post", _no_post)
    eng = GreyLineLiveBrokerClientEngine(access_token="tok", base_url="https://api.tradestation.com/v3")
    with pytest.raises(LiveOrderSafetyError):
        eng.submit_order("AAPL", 1, "BUY")


def test_blocks_production_target_without_confirmation(monkeypatch):
    # Even if the live switches are on, a PRODUCTION target needs explicit confirmation.
    monkeypatch.setenv("GREYLINE_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("GREYLINE_LIVE_ORDER_PLACEMENT_ALLOWED", "true")
    monkeypatch.setenv("GREYLINE_LIVE_PRODUCTION_CONFIRMED", "false")
    monkeypatch.setenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")  # guard sees sandbox
    monkeypatch.setattr(M.requests, "post", _no_post)
    eng = GreyLineLiveBrokerClientEngine(access_token="tok", base_url="https://api.tradestation.com/v3")
    with pytest.raises(LiveOrderSafetyError):
        eng.submit_order("AAPL", 1, "BUY")   # target is production -> refused
