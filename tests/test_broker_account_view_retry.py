"""Broker account view — only-refetch-the-FAILED-sub-read retry.

Under load one of the three reads (balance/positions/orders) intermittently STARVES (transient non-200,
NOT a 429). The retry must (a) keep a sub-read once it lands a good 200, re-fetching ONLY the still-failing
leg, (b) converge to a clean reads_ok=True read across attempts, (c) still respect 429 (never retry into
the throttle), and (d) never fabricate — a persistent failure fails-closed. All three TS engines are
stubbed; no network, no orders."""

import pytest

import app.services.broker_account_view_engine as mod
from app.services.broker_account_view_engine import BrokerAccountViewEngine


_GOOD_BAL = {"http_status": 200, "response_json": {"Balances": [
    {"Equity": "10000", "CashBalance": "5000", "BuyingPower": "5000"}]}}
_GOOD_POS = {"http_status": 200, "response_json": {"Positions": []}}
_GOOD_ORD = {"http_status": 200, "response_json": {"Orders": []}}


class _Seq:
    """Returns the next scripted response each call, and records the call count."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, *a, **k):
        r = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return r


@pytest.fixture(autouse=True)
def _no_sleep_real_source(monkeypatch):
    # never actually sleep in the retry; resolve to a healthy paper account
    monkeypatch.setattr(mod, "_t", __import__("time"), raising=False)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(mod.TradeStationAccountSourceEngine, "resolve",
                        lambda self: {"ok": True, "mode": "paper", "account_id": "SIM3288615M",
                                      "label": "TradeStation Paper Trading Account", "host_kind": "sim"})
    mod._SNAPSHOT_CACHE.clear()          # isolate the shared read-through cache between tests
    # default: no cache unless a test opts in (so retry/429 tests see every read fresh)
    monkeypatch.setenv("GREYLINE_POSITIONS_CACHE_TTL_S", "0")
    yield
    mod._SNAPSHOT_CACHE.clear()


def _wire(monkeypatch, bal_seq, pos_seq, ord_seq):
    b, p, o = _Seq(bal_seq), _Seq(pos_seq), _Seq(ord_seq)
    monkeypatch.setattr(mod.TradeStationBalanceLiveEngine, "get_balance", lambda self, _b=b: _b())
    monkeypatch.setattr(mod.TradeStationPositionsLiveEngine, "get_positions", lambda self, _p=p: _p())
    monkeypatch.setattr(mod.TradeStationOrdersLiveEngine, "get_orders", lambda self, _o=o: _o())
    return b, p, o


def test_clean_read_first_try_no_refetch(monkeypatch):
    b, p, o = _wire(monkeypatch, [_GOOD_BAL], [_GOOD_POS], [_GOOD_ORD])
    snap = BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is True and snap["status"] == "BROKER_ACCOUNT_VIEW_READY"
    assert snap["equity"] == 10000.0
    # one call each — a clean read never retries
    assert (b.calls, p.calls, o.calls) == (1, 1, 1)


def test_only_failing_leg_is_refetched(monkeypatch):
    # balance + orders clean on the first call; POSITIONS starves once (timeout) then succeeds.
    starve = {"http_status": None, "response_json": None}
    b, p, o = _wire(monkeypatch, [_GOOD_BAL], [starve, _GOOD_POS], [_GOOD_ORD])
    snap = BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is True
    # balance/orders landed 200 on attempt 1 and are NOT re-fetched; only positions is retried.
    assert b.calls == 1 and o.calls == 1
    assert p.calls == 2


def test_converges_when_each_leg_flaps_once(monkeypatch):
    starve = {"http_status": None, "response_json": None}
    b, p, o = _wire(monkeypatch,
                    [starve, _GOOD_BAL],
                    [_GOOD_POS],
                    [starve, _GOOD_ORD])
    snap = BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is True and snap["equity"] == 10000.0


def test_429_stops_immediately_fails_closed(monkeypatch):
    throttled = {"http_status": 429, "response_json": None}
    b, p, o = _wire(monkeypatch, [_GOOD_BAL], [throttled], [_GOOD_ORD])
    snap = BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is False
    assert snap["read_rate_limited"] is True
    assert snap["status"] == "BROKER_ACCOUNT_READ_DEGRADED"
    # respected the throttle: positions fetched once, then the loop broke (no retry into the 429)
    assert p.calls == 1


def test_persistent_failure_fails_closed_never_fabricates(monkeypatch):
    monkeypatch.setenv("GREYLINE_BROKER_READ_ATTEMPTS", "3")
    starve = {"http_status": None, "response_json": None}
    b, p, o = _wire(monkeypatch, [_GOOD_BAL], [starve], [_GOOD_ORD])
    snap = BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is False
    assert snap["status"] == "BROKER_ACCOUNT_READ_DEGRADED"
    # tried the configured number of attempts on the failing leg
    assert p.calls == 3
    # the failed leg is honestly empty; consumers gate on reads_ok=False (a value parsed from the
    # one REAL 200 leg is not a fabrication, but the view is flagged degraded so it isn't trusted).
    assert snap["positions"] == []
    assert snap["read_detail"] and "positions" in snap["read_detail"]


def test_cache_collapses_repeat_reads(monkeypatch):
    # a good read is cached; the next call within TTL serves it WITHOUT hitting TS again (the 429 fix)
    monkeypatch.setenv("GREYLINE_POSITIONS_CACHE_TTL_S", "30")
    mod._SNAPSHOT_CACHE.clear()
    b, p, o = _wire(monkeypatch, [_GOOD_BAL], [_GOOD_POS], [_GOOD_ORD])
    eng = BrokerAccountViewEngine()
    first = eng.snapshot()
    assert first["reads_ok"] is True and not first.get("served_from_cache")
    second = eng.snapshot()
    assert second["served_from_cache"] is True and second["cache_age_seconds"] is not None
    # crucially: the second call made NO new TS calls — the burst collapsed to one real read
    assert (b.calls, p.calls, o.calls) == (1, 1, 1)


def test_degraded_read_is_never_cached(monkeypatch):
    monkeypatch.setenv("GREYLINE_POSITIONS_CACHE_TTL_S", "30")
    monkeypatch.setenv("GREYLINE_BROKER_READ_ATTEMPTS", "1")
    mod._SNAPSHOT_CACHE.clear()
    throttled = {"http_status": 429, "response_json": None}
    _wire(monkeypatch, [_GOOD_BAL], [throttled], [_GOOD_ORD])
    snap = BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is False
    # nothing good to cache -> the account key must be absent (a degraded view is never served later)
    assert "SIM3288615M" not in mod._SNAPSHOT_CACHE


def test_allow_cache_false_forces_fresh(monkeypatch):
    monkeypatch.setenv("GREYLINE_POSITIONS_CACHE_TTL_S", "30")
    mod._SNAPSHOT_CACHE.clear()
    b, p, o = _wire(monkeypatch, [_GOOD_BAL], [_GOOD_POS], [_GOOD_ORD])
    eng = BrokerAccountViewEngine()
    eng.snapshot()                              # populates cache
    fresh = eng.snapshot(allow_cache=False)     # must bypass and re-read
    assert not fresh.get("served_from_cache")
    assert (b.calls, p.calls, o.calls) == (2, 2, 2)


def test_empty_balance_body_is_not_ok(monkeypatch):
    mod._SNAPSHOT_CACHE.clear()
    # HTTP 200 but empty Balances (gateway interstitial) must NOT read as healthy
    monkeypatch.setenv("GREYLINE_BROKER_READ_ATTEMPTS", "2")
    empty_bal = {"http_status": 200, "response_json": {"Balances": []}}
    _wire(monkeypatch, [empty_bal], [_GOOD_POS], [_GOOD_ORD])
    snap = BrokerAccountViewEngine().snapshot()
    assert snap["reads_ok"] is False and snap["equity"] == 0.0
