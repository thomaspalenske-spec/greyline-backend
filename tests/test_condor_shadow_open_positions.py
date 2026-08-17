"""Per-open-condor rows for the dashboard: short-premium P/L = (entry credit − current mark) × 100 ×
quantity, % = share of the entry credit captured; unpriceable legs stay None (never fabricated). The
100× multiplier is the real options contract multiplier and quantity is the condor's actual size — this
is NOT the underlying shadows' hypothetical 100-share lot. Read-only, no orders.
"""

from app.services.condor_shadow_engine import CondorShadowEngine


def _cond(**kw):
    base = {"status": "OPEN", "symbol": "SPY", "sleeve": "vrp", "expiration": "2026-09-18",
            "entry_credit_mid": 1.00, "quantity": 1, "legs": {}}
    base.update(kw)
    return base


def test_short_premium_pnl_and_pct(monkeypatch):
    e = CondorShadowEngine()
    monkeypatch.setattr(e, "_entries", lambda: [_cond(entry_credit_mid=1.00, quantity=2)])
    monkeypatch.setattr(e, "_current_value", lambda legs: 0.40)   # condor decayed 1.00 -> 0.40 = profit
    monkeypatch.setattr(e, "_et_date", lambda: "2026-09-01")
    row = e.open_positions()[0]
    assert row["contracts"] == 2
    assert row["entry_credit"] == 1.0 and row["current_value"] == 0.4
    assert row["pnl_dollars"] == 120.0        # (1.00 − 0.40) × 100 × 2
    assert row["pnl_pct"] == 60.0             # 60% of the credit captured
    assert row["dte"] == 17                    # 2026-09-18 − 2026-09-01


def test_losing_short_condor_is_negative(monkeypatch):
    e = CondorShadowEngine()
    monkeypatch.setattr(e, "_entries", lambda: [_cond(entry_credit_mid=1.00, quantity=1)])
    monkeypatch.setattr(e, "_current_value", lambda legs: 1.75)   # widened against us
    monkeypatch.setattr(e, "_et_date", lambda: "2026-09-01")
    row = e.open_positions()[0]
    assert row["pnl_dollars"] == -75.0 and row["pnl_pct"] == -75.0


def test_unpriceable_condor_has_no_fabricated_pnl(monkeypatch):
    e = CondorShadowEngine()
    monkeypatch.setattr(e, "_entries", lambda: [_cond()])
    monkeypatch.setattr(e, "_current_value", lambda legs: None)   # legs not quotable this cycle
    monkeypatch.setattr(e, "_et_date", lambda: "2026-09-01")
    row = e.open_positions()[0]
    assert row["contracts"] == 1 and row["entry_credit"] == 1.0
    assert "pnl_dollars" not in row and "current_value" not in row


def test_closed_condors_are_excluded(monkeypatch):
    e = CondorShadowEngine()
    monkeypatch.setattr(e, "_entries", lambda: [_cond(status="CLOSED"), _cond(symbol="QQQ")])
    monkeypatch.setattr(e, "_current_value", lambda legs: 0.5)
    monkeypatch.setattr(e, "_et_date", lambda: "2026-09-01")
    rows = e.open_positions()
    assert len(rows) == 1 and rows[0]["symbol"] == "QQQ"
