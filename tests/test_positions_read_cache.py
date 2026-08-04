"""Shared per-cycle positions cache: collapse the read storm that triggers TradeStation 429s, WITHOUT
masking a real degraded read.

A CONFIRMED-good (200) read is cached for the TTL; subsequent calls within it reuse it (no API hit). A
429/failure is never cached and never served — it always surfaces. Invalidation (post-order) forces a
fresh read.
"""

import app.services.tradestation_positions_live_engine as mod
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine as P


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.text = "{}"

    def json(self):
        return {"Positions": [{"Symbol": "USMV", "Quantity": 3}]} if self.status_code == 200 else {}


def _setup(monkeypatch, statuses):
    """Route resolution to a fixed paper account; feed a scripted sequence of HTTP statuses; count hits."""
    P.invalidate()
    monkeypatch.setenv("TRADESTATION_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(mod, "reload_env", lambda *a, **k: None, raising=False)

    import app.services.tradestation_account_source_engine as src_mod
    monkeypatch.setattr(src_mod.TradeStationAccountSourceEngine, "resolve",
                        lambda self: {"ok": True, "account_id": "SIM999", "base_url": "https://x", "mode": "paper"})
    calls = {"n": 0}
    seq = list(statuses)

    def fake_get(url, **k):
        calls["n"] += 1
        return _Resp(seq.pop(0) if seq else 200)

    monkeypatch.setattr(mod.requests, "get", fake_get)
    return calls


def test_second_read_within_ttl_hits_cache_not_api(monkeypatch):
    calls = _setup(monkeypatch, [200, 200, 200])
    r1 = P().get_positions()
    r2 = P().get_positions()
    r3 = P().get_positions()
    assert calls["n"] == 1                              # only ONE real API hit
    assert r1["served_from_cache"] is False
    assert r2["served_from_cache"] is True and r3["served_from_cache"] is True
    assert r2["response_json"]["Positions"][0]["Symbol"] == "USMV"


def test_429_is_never_cached_and_always_surfaces(monkeypatch):
    calls = _setup(monkeypatch, [429, 429])
    r1 = P().get_positions()
    r2 = P().get_positions()
    assert r1["http_status"] == 429 and r2["http_status"] == 429
    assert r1["served_from_cache"] is False and r2["served_from_cache"] is False
    assert calls["n"] == 2                              # a failure never serves from cache


def test_429_after_good_read_does_not_serve_stale_once_ttl_expected_off(monkeypatch):
    # a good read is cached; but with the cache DISABLED (ttl=0) a later call must hit the API again
    monkeypatch.setenv("GREYLINE_POSITIONS_CACHE_TTL_S", "0")
    calls = _setup(monkeypatch, [200, 200])
    P().get_positions()
    r2 = P().get_positions()
    assert calls["n"] == 2 and r2["served_from_cache"] is False


def test_invalidate_forces_fresh_read(monkeypatch):
    calls = _setup(monkeypatch, [200, 200])
    P().get_positions()
    P.invalidate()
    P().get_positions()
    assert calls["n"] == 2                              # invalidation dropped the cache → new API hit
