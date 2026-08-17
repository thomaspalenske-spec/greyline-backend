"""Balance read must share a short-TTL cache (like positions) so the reliability core / money tiles /
commander summary don't each hit TradeStation fresh and rate-limit US (the 2026-08-09 self-throttle:
uncached balance -> HTTP 429 -> balance_ok=False -> Mission Status YELLOW).

Cache ONLY a genuinely-good read (200 WITH a Balances record). A 429/failure/empty body is never cached
and never served, so a real degraded read still surfaces.
"""

import app.services.tradestation_balance_live_engine as mod
from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine as B


class _Resp:
    def __init__(self, status, json_body, text="x"):
        self.status_code = status
        self._j = json_body
        self.text = text
        self.headers = {}
        self.closed = False

    def iter_content(self, chunk_size=65536):        # engine now streams the body under a total deadline
        import json as _j
        yield (_j.dumps(self._j).encode() if self._j is not None else b"")

    def close(self):
        self.closed = True

    def json(self):
        if self._j is None:
            raise ValueError("no json")
        return self._j


def _setup(monkeypatch, responses):
    import app.services.tradestation_account_source_engine as srcmod
    monkeypatch.setattr(srcmod.TradeStationAccountSourceEngine, "resolve",
                        lambda self: {"ok": True, "account_id": "SIM1", "base_url": "https://sim",
                                      "mode": "paper", "host_kind": "sim"})
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(mod, "reload_env", lambda *a, **k: None)   # keep the test env authoritative
    calls = {"n": 0}
    it = iter(responses)
    monkeypatch.setattr(mod.requests, "get", lambda url, **k: (calls.__setitem__("n", calls["n"] + 1) or next(it)))
    B.invalidate()                                                  # clean cache between tests
    return calls


def test_good_balance_is_cached_and_served(monkeypatch):
    calls = _setup(monkeypatch, [_Resp(200, {"Balances": [{"Equity": "10000"}]}),
                                 _Resp(200, {"Balances": [{"Equity": "999"}]})])
    r1 = B().get_balance()
    r2 = B().get_balance()
    assert calls["n"] == 1                      # second read served from cache — one API hit, not two
    assert r1["http_status"] == 200 and r1["served_from_cache"] is False
    assert r2["served_from_cache"] is True and r2["cache_age_s"] >= 0


def test_429_is_never_cached(monkeypatch):
    calls = _setup(monkeypatch, [_Resp(429, None), _Resp(429, None)])
    B().get_balance()
    r2 = B().get_balance()
    assert calls["n"] == 2                       # a throttle is never cached -> re-read (surfaces the real state)
    assert r2["http_status"] == 429


def test_200_with_empty_body_is_never_cached(monkeypatch):
    # a gateway interstitial (200, no Balances) must NOT be cached as good, or it masks a degraded read
    calls = _setup(monkeypatch, [_Resp(200, {}), _Resp(200, {"Balances": [{"Equity": "1"}]})])
    B().get_balance()
    r2 = B().get_balance()
    assert calls["n"] == 2
    assert r2["served_from_cache"] is False


def test_invalidate_forces_a_fresh_read(monkeypatch):
    calls = _setup(monkeypatch, [_Resp(200, {"Balances": [{"Equity": "1"}]}),
                                 _Resp(200, {"Balances": [{"Equity": "2"}]})])
    B().get_balance()
    B.invalidate()
    B().get_balance()
    assert calls["n"] == 2                        # invalidate drops the cache -> next call re-hits
