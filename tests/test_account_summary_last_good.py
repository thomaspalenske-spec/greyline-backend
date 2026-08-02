"""Account summary last-known-good: a transient broker-read failure must serve the last confirmed money
figures (clearly aged) instead of blanking every tile — while NEVER inventing numbers (last_good is a real
prior reading or absent). Honest degraded UX: live=unknown, plus the last real reading and how old it is."""

import json

import app.routes.account_summary as mod
import app.services.mission_realized_pnl_engine as mrp


def _no_realized(monkeypatch):
    monkeypatch.setattr(mrp.MissionRealizedPnlEngine, "cumulative_realized", lambda self: 0.0)


def _good_view():
    # a healthy broker snapshot with one $100-cost position marked +$5
    return {"reads_ok": True, "account_mode": "paper", "account_label": "TradeStation Paper Trading Account",
            "positions": [{"symbol": "GLW", "entry_price": 100.0, "quantity": 1.0,
                           "current_price": 105.0, "unrealized_pnl": 5.0}],
            "equity": 1000000.0, "cash_balance": 1.0, "buying_power": 1.0, "orders_working": 0}


def _degraded_view():
    return {"reads_ok": False, "account_mode": "paper", "account_label": "TradeStation Paper Trading Account",
            "positions": [], "status": "BROKER_ACCOUNT_READ_DEGRADED"}


def test_success_caches_and_degraded_serves_last_good(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_LAST_GOOD", tmp_path / "lg.json")
    monkeypatch.setattr(mod, "getenv", lambda k, d=None: "10000" if "CAPITAL_BASE" in k else (d or ""))
    _no_realized(monkeypatch)

    # 1) a healthy read publishes real numbers AND caches them
    monkeypatch.setattr(mod, "BrokerAccountViewEngine", lambda: type("V", (), {"snapshot": lambda s: _good_view()})())
    ok = mod.account_summary()
    assert ok["status"] == "ACCOUNT_SUMMARY_READY" and ok["total_equity"] == 10005.0
    assert (tmp_path / "lg.json").exists()

    # 2) a degraded read blanks the LIVE tiles but carries last_good (aged), never fabricating
    monkeypatch.setattr(mod, "BrokerAccountViewEngine", lambda: type("V", (), {"snapshot": lambda s: _degraded_view()})())
    deg = mod.account_summary()
    assert deg["status"] == "ACCOUNT_SUMMARY_BROKER_READ_DEGRADED"
    assert deg["degraded"] is True and deg["total_equity"] is None      # live figure is honestly unknown
    lg = deg["last_good"]
    assert lg is not None and lg["total_equity"] == 10005.0             # last confirmed reading is served
    assert "age_seconds" in lg


def test_degraded_with_no_prior_good_has_null_last_good(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_LAST_GOOD", tmp_path / "absent.json")    # nothing cached yet
    monkeypatch.setattr(mod, "getenv", lambda k, d=None: "10000" if "CAPITAL_BASE" in k else (d or ""))
    monkeypatch.setattr(mod, "BrokerAccountViewEngine", lambda: type("V", (), {"snapshot": lambda s: _degraded_view()})())
    _no_realized(monkeypatch)
    deg = mod.account_summary()
    assert deg["degraded"] is True and deg["last_good"] is None         # no fabrication when nothing cached


def test_last_good_roundtrip_has_age(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_LAST_GOOD", tmp_path / "lg.json")
    (tmp_path / "lg.json").write_text(json.dumps({"as_of": "2026-08-01T00:00:00", "total_equity": 9999.0}))
    lg = mod._load_last_good()
    assert lg["total_equity"] == 9999.0 and lg["age_seconds"] is not None and lg["age_seconds"] >= 0
