"""TradeStation warned about excessive refresh-token exchanges (2026-07-28). These lock in the fix:
the refresh endpoint is hit at most once per interval (hard throttle at the choke point), and the
maintenance engine only refreshes when the token is genuinely near expiry (not after 5 min of a 20).
"""

from datetime import datetime, timedelta

import app.services.tradestation_token_refresh_engine as rmod
import app.services.tradestation_token_maintenance_engine as mmod
from app.services.tradestation_token_refresh_engine import TradeStationTokenRefreshEngine as R
from app.services.tradestation_token_maintenance_engine import TradeStationTokenMaintenanceEngine as M


class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"access_token": "AAA", "expires_in": 1200, "refresh_token": "RRR"}


def _mock_refresh(monkeypatch):
    posts = []
    monkeypatch.setattr(rmod, "reload_env", lambda: None)
    monkeypatch.setattr(rmod.requests, "post", lambda *a, **k: (posts.append(1), _Resp())[1])
    monkeypatch.setattr(rmod, "set_key", lambda *a, **k: None)
    monkeypatch.setattr(rmod, "ImmutableAuditLedgerEngine",
                        lambda: type("L", (), {"record": lambda self, *a, **k: None})())
    monkeypatch.setenv("TRADESTATION_API_KEY", "k")
    monkeypatch.setenv("TRADESTATION_API_SECRET", "s")
    monkeypatch.setenv("TRADESTATION_REFRESH_TOKEN", "r")
    R._last_attempt_at = None
    return posts


def test_single_refresh_hits_endpoint_once(monkeypatch):
    posts = _mock_refresh(monkeypatch)
    r = R().refresh()
    assert r["token_refreshed"] is True and len(posts) == 1


def test_rapid_second_refresh_is_throttled(monkeypatch):
    posts = _mock_refresh(monkeypatch)
    R().refresh()                                   # 1st: real exchange
    r2 = R().refresh()                              # 2nd, immediately after
    assert r2["status"] == "TOKEN_REFRESH_THROTTLED" and r2["token_refreshed"] is False
    assert len(posts) == 1                          # endpoint NOT hit a second time


def test_force_bypasses_throttle(monkeypatch):
    posts = _mock_refresh(monkeypatch)
    R().refresh()
    R().refresh(force=True)
    assert len(posts) == 2


def test_throttle_lifts_after_interval(monkeypatch):
    posts = _mock_refresh(monkeypatch)
    R().refresh()
    R._last_attempt_at = datetime.utcnow() - timedelta(seconds=R.MIN_REFRESH_INTERVAL_SEC + 1)
    R().refresh()                                   # interval elapsed -> allowed
    assert len(posts) == 2


def _mock_maint(monkeypatch, refreshed):
    monkeypatch.setattr(mmod, "reload_env", lambda: None)   # so setenv sticks (the .env precedence trap)
    monkeypatch.setattr(mmod, "TradeStationTokenRefreshEngine",
                        lambda: type("X", (), {"refresh": lambda self, *a, **k:
                                               (refreshed.append(1), {"status": "OK", "token_refreshed": True})[1]})())
    M._last_refresh_at = None


def test_fresh_token_is_not_refreshed(monkeypatch):
    refreshed = []
    _mock_maint(monkeypatch, refreshed)
    monkeypatch.setenv("TRADESTATION_TOKEN_SAVED_AT", datetime.utcnow().isoformat())
    monkeypatch.setenv("TRADESTATION_TOKEN_EXPIRES_IN", "1200")
    r = M().evaluate()
    assert r["should_refresh"] is False and refreshed == []   # ~1200s left >> 120 buffer: reuse it


def test_near_expiry_token_is_refreshed(monkeypatch):
    refreshed = []
    _mock_maint(monkeypatch, refreshed)
    monkeypatch.setenv("TRADESTATION_TOKEN_SAVED_AT", (datetime.utcnow() - timedelta(seconds=1150)).isoformat())
    monkeypatch.setenv("TRADESTATION_TOKEN_EXPIRES_IN", "1200")
    r = M().evaluate()
    assert r["should_refresh"] is True and len(refreshed) == 1   # ~50s left < 120 buffer

    # ...but a fresh token 5 minutes old is NOT refreshed (the old 900s-buffer bug)
    refreshed.clear(); M._last_refresh_at = None
    monkeypatch.setenv("TRADESTATION_TOKEN_SAVED_AT", (datetime.utcnow() - timedelta(seconds=300)).isoformat())
    assert M().evaluate()["should_refresh"] is False and refreshed == []
