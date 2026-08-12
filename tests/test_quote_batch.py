"""Batch quotes: the condor manager priced 16 legs with 16 SERIAL, throttle-bound TS round-trips (+ a
per-call token check) — the single biggest scheduler-cycle cost. get_quotes fetches them in ONE request;
_prefetch_leg_quotes uses it (serial get_quote fallback if the engine lacks it). Behavior-preserving."""

import app.services.tradestation_quote_live_engine as qmod
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine as Q
from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine as V


class _Resp:
    status_code = 200
    headers = {}

    def __init__(self, quotes):
        self._q = quotes
        self.closed = False

    def iter_content(self, chunk_size=65536):        # engine now streams the body under a total deadline
        import json as _j
        yield _j.dumps({"Quotes": self._q}).encode()

    def close(self):
        self.closed = True


def test_get_quotes_batches_one_request(monkeypatch):
    Q.clear_cache()
    calls = {"n": 0, "urls": []}

    def _get(url, params=None, headers=None, timeout=None, stream=False):
        calls["n"] += 1
        calls["urls"].append(url)
        return _Resp([{"Symbol": "AAA", "Bid": 1.0, "Ask": 1.2},
                      {"Symbol": "BBB", "Bid": 2.0, "Ask": 2.4}])
    monkeypatch.setattr(qmod.requests, "get", _get)
    monkeypatch.setattr(qmod, "getenv", lambda k, d="": "tok" if "TOKEN" in k else d)
    monkeypatch.setattr("app.services.tradestation_token_maintenance_engine.TradeStationTokenMaintenanceEngine.evaluate",
                        lambda self: {})
    out = Q().get_quotes(["AAA", "BBB"])
    assert calls["n"] == 1                                   # ONE request for both symbols
    assert "AAA,BBB" in calls["urls"][0]
    assert out["AAA"]["response_json"]["Quotes"][0]["Bid"] == 1.0
    assert out["BBB"]["status"] == "QUOTE_READ_SUCCESS"


def test_get_quotes_serves_cache_without_network(monkeypatch):
    Q.clear_cache()
    n = {"c": 0}

    def _get(url, params=None, headers=None, timeout=None, stream=False):
        n["c"] += 1
        return _Resp([{"Symbol": "AAA", "Bid": 1.0, "Ask": 1.2}])
    monkeypatch.setattr(qmod.requests, "get", _get)
    monkeypatch.setattr(qmod, "getenv", lambda k, d="": "tok" if "TOKEN" in k else d)
    monkeypatch.setattr("app.services.tradestation_token_maintenance_engine.TradeStationTokenMaintenanceEngine.evaluate",
                        lambda self: {})
    Q().get_quotes(["AAA"])
    Q().get_quotes(["AAA"])                                  # second call is a fresh cache hit
    assert n["c"] == 1


class _BatchQ:
    """A quote engine that ONLY supports the batch call (exercises the primary path)."""
    def get_quotes(self, syms):
        m = {"X 261218C110": (0.50, 0.60), "X 261218C115": (0.20, 0.30),
             "X 261218P90": (0.55, 0.65), "X 261218P85": (0.22, 0.32)}
        out = {}
        for s in syms:
            bid, ask = m.get(s, (0.0, 0.0))
            out[str(s).upper()] = {"response_json": {"Quotes": [{"Bid": bid, "Ask": ask}]}}
        return out


def test_prefetch_uses_batch_path():
    legs = ["X 261218C110", "X 261218C115", "X 261218P90", "X 261218P85"]
    out = V()._prefetch_leg_quotes(_BatchQ(), legs)
    assert out["X 261218C110"] == (0.50, 0.60) and out["X 261218P85"] == (0.22, 0.32)


class _SerialOnlyQ:
    """No get_quotes -> _prefetch_leg_quotes must fall back to serial get_quote."""
    def get_quote(self, s):
        return {"response_json": {"Quotes": [{"Bid": 1.0, "Ask": 1.5}]}}


def test_prefetch_falls_back_to_serial_when_no_batch():
    out = V()._prefetch_leg_quotes(_SerialOnlyQ(), ["X 261218C110", "X 261218P90"])
    assert out["X 261218C110"] == (1.0, 1.5) and out["X 261218P90"] == (1.0, 1.5)
