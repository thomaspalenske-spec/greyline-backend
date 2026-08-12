"""The broker account read must RESPECT a 429 (rate limit), not retry into it.

BrokerAccountViewEngine bounded-retries a degraded read 4x to catch a clear window. But an HTTP 429 means
"you are calling too often" — retrying amplifies it (4 rapid calls hold the throttle open longer, and
TradeStation has flagged us for excessive calls before). On a 429 the loop must stop after ONE round and
fail-closed, while a plain (non-429) failure still gets the full bounded retry.
"""

import app.services.broker_account_view_engine as mod
from app.services.broker_account_view_engine import BrokerAccountViewEngine

_SRC = {"ok": True, "mode": "paper", "label": "SIM", "account_id": "SIM1", "host_kind": "sim"}


def _patch_source(monkeypatch):
    monkeypatch.setattr(mod.TradeStationAccountSourceEngine, "resolve", lambda self: dict(_SRC))
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)      # no real backoff delay in tests


def test_429_is_not_retried_no_amplification(monkeypatch):
    _patch_source(monkeypatch)
    calls = {"balance": 0, "positions": 0, "orders": 0}

    def _bal(self):
        calls["balance"] += 1
        return {"http_status": 429, "response_json": None}

    monkeypatch.setattr(mod.TradeStationBalanceLiveEngine, "get_balance", _bal)
    monkeypatch.setattr(mod.TradeStationPositionsLiveEngine, "get_positions",
                        lambda self: (calls.__setitem__("positions", calls["positions"] + 1),
                                      {"http_status": 429, "response_json": None})[1])
    monkeypatch.setattr(mod.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: (calls.__setitem__("orders", calls["orders"] + 1),
                                      {"http_status": 429, "response_json": None})[1])

    v = BrokerAccountViewEngine().snapshot()
    assert calls["balance"] == 1, calls        # exactly ONE round — the 429 stopped the retry
    assert v["reads_ok"] is False
    assert v["read_rate_limited"] is True
    assert "429" in v["read_detail"] and "rate-limited" in v["read_detail"]
    assert v["read_broker_side"] is False      # 429 is a throttle, not a 5xx broker outage


def test_non_429_failure_still_uses_bounded_retry(monkeypatch):
    _patch_source(monkeypatch)
    monkeypatch.setenv("GREYLINE_BROKER_READ_ATTEMPTS", "4")     # pin attempts (default is tuned separately)
    calls = {"n": 0}

    def _bal(self):
        calls["n"] += 1
        return {"http_status": 200, "response_json": {}}        # 200 but EMPTY Balances -> not reads_ok

    monkeypatch.setattr(mod.TradeStationBalanceLiveEngine, "get_balance", _bal)
    monkeypatch.setattr(mod.TradeStationPositionsLiveEngine, "get_positions",
                        lambda self: {"http_status": 200, "response_json": {"Positions": []}})
    monkeypatch.setattr(mod.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"http_status": 200, "response_json": {"Orders": []}})

    v = BrokerAccountViewEngine().snapshot()
    assert calls["n"] == 4                       # no 429 -> full bounded retry to catch a clear window
    assert v["reads_ok"] is False
    assert v["read_rate_limited"] is False


def test_clean_read_breaks_immediately(monkeypatch):
    _patch_source(monkeypatch)
    calls = {"n": 0}

    def _bal(self):
        calls["n"] += 1
        return {"http_status": 200, "response_json": {"Balances": [{"Equity": "10000", "CashBalance": "10000",
                                                                     "BuyingPower": "10000"}]}}

    monkeypatch.setattr(mod.TradeStationBalanceLiveEngine, "get_balance", _bal)
    monkeypatch.setattr(mod.TradeStationPositionsLiveEngine, "get_positions",
                        lambda self: {"http_status": 200, "response_json": {"Positions": []}})
    monkeypatch.setattr(mod.TradeStationOrdersLiveEngine, "get_orders",
                        lambda self: {"http_status": 200, "response_json": {"Orders": []}})

    v = BrokerAccountViewEngine().snapshot()
    assert calls["n"] == 1 and v["reads_ok"] is True and v["read_rate_limited"] is False
