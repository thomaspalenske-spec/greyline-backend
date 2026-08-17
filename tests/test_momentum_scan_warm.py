"""Momentum scan warm: opt-in gate, once/day gate, writes the shared cache, fail-safe on compute error.
The heavy _compute is stubbed — no network, no real TS fetch."""

import json

import pytest

from app.services.momentum_scan_warm_engine import MomentumScanWarmEngine as W


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "MARKER", tmp_path / "scan_warm_last.json")
    yield


def _stub_compute(monkeypatch, tmp_path, result):
    import app.routes.top_candidates as tc
    monkeypatch.setattr(tc, "CACHE", tmp_path / "top_candidates_cache.json")
    monkeypatch.setattr(tc, "_compute", lambda n: dict(result))
    return tc


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GREYLINE_MOMENTUM_SCAN_WARM", raising=False)
    assert W().warm_if_due({})["status"] == "MOM_SCAN_WARM_DISABLED"


def test_warms_once_then_skips_same_day(monkeypatch, tmp_path):
    monkeypatch.setenv("GREYLINE_MOMENTUM_SCAN_WARM", "true")
    tc = _stub_compute(monkeypatch, tmp_path, {"data_source": "TRADESTATION_LIVE",
                                               "candidates": [{"symbol": "AAA"}]})
    mh = {"market_time": "2026-08-10T17:00:00"}
    r1 = W().warm_if_due(mh)
    assert r1["status"] == "MOM_SCAN_WARM_DONE" and r1["ran"] is True and r1["data_source"] == "TRADESTATION_LIVE"
    assert json.loads(tc.CACHE.read_text())["data_source"] == "TRADESTATION_LIVE"   # cache written
    # same ET day -> must NOT re-run the heavy fetch
    r2 = W().warm_if_due(mh)
    assert r2["status"] == "MOM_SCAN_WARM_ALREADY_TODAY" and r2["ran"] is False


def test_new_day_warms_again(monkeypatch, tmp_path):
    monkeypatch.setenv("GREYLINE_MOMENTUM_SCAN_WARM", "true")
    _stub_compute(monkeypatch, tmp_path, {"data_source": "TRADESTATION_LIVE", "candidates": []})
    W().warm_if_due({"market_time": "2026-08-10T17:00:00"})
    r = W().warm_if_due({"market_time": "2026-08-11T17:00:00"})     # next ET day
    assert r["status"] == "MOM_SCAN_WARM_DONE" and r["ran"] is True


def test_compute_failure_is_fail_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("GREYLINE_MOMENTUM_SCAN_WARM", "true")
    import app.routes.top_candidates as tc

    def _boom(n):
        raise RuntimeError("TS fetch failed")
    monkeypatch.setattr(tc, "CACHE", tmp_path / "top_candidates_cache.json")
    monkeypatch.setattr(tc, "_compute", _boom)
    r = W().warm_if_due({"market_time": "2026-08-10T17:00:00"})
    assert r["status"] == "MOM_SCAN_WARM_DEGRADED" and r["ran"] is False
    assert not (tmp_path / "top_candidates_cache.json").exists()    # last good cache left untouched
    assert W()._last_warm_date() == ""                             # not marked done -> retries next cycle
