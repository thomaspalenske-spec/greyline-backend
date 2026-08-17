"""On cohort settlement the momentum shadow messages the operator the $/% P/L (once per cohort, gated).
Hermetic — the alert engine's dispatch is captured, no real iMessage."""

import app.services.external_alert_engine as aem
from app.services.momentum_reversal_shadow_engine import MomentumReversalShadowEngine as M


def _rec():
    return {"opened": "2026-08-10", "cost_roundtrip_bps": 10.0, "gross_return": 0.0598, "net_return": 0.0588,
            "legs": [{"symbol": "BRUN", "side": "BUY", "gross_return": 0.34},
                     {"symbol": "VOR", "side": "SELL", "gross_return": 0.017}]}


def test_settle_alert_reports_dollar_and_pct(monkeypatch):
    captured = {}
    monkeypatch.setattr(aem.ExternalAlertEngine, "dispatch",
                        lambda self, **k: captured.update(k) or {"status": "SENT"})
    monkeypatch.delenv("GREYLINE_MOMENTUM_SHADOW_SETTLE_ALERT", raising=False)
    monkeypatch.setenv("GREYLINE_MOMENTUM_SHADOW_NOTIONAL_USD", "10000")
    M()._report_settled(_rec())
    msg = captured.get("message", "")
    assert "net +5.88%" in msg and "gross +5.98%" in msg          # % P/L, both net + gross
    assert "$+588.00" in msg                                       # $ P/L on the $10k notional
    assert "ZERO-capital" in msg                                   # honest: not a real fill
    assert captured.get("fingerprint") == "MOMENTUM_SHADOW_SETTLED:2026-08-10"   # fires once per cohort


def test_settle_alert_gated_off(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(aem.ExternalAlertEngine, "dispatch", lambda self, **k: called.update(n=called["n"] + 1))
    monkeypatch.setenv("GREYLINE_MOMENTUM_SHADOW_SETTLE_ALERT", "false")
    M()._report_settled(_rec())
    assert called["n"] == 0                                        # gated off → no message


def test_settle_alert_never_raises(monkeypatch):
    monkeypatch.setattr(aem.ExternalAlertEngine, "dispatch",
                        lambda self, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    M()._report_settled(_rec())   # must swallow — never block mark()
