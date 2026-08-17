"""THE RULE: a zero-capital shadow may only record an open/settle when the transaction could actually
have executed on TradeStation at that moment. Locks the single shared gate + its class-aware application
in a representative equity shadow (ETF) and a futures shadow. Read-only: never places an order.
"""

import json

import app.services.shadow_tradeability_gate as gate


class _MH:
    def __init__(self, **kw):
        self._s = kw

    def status(self):
        return self._s


def _patch_mh(monkeypatch, **status):
    monkeypatch.setattr(gate, "_market_status", lambda: status)


# ---- the shared gate ------------------------------------------------------------------------------

def test_equity_gate_true_only_in_regular_session(monkeypatch):
    _patch_mh(monkeypatch, is_regular_session=True, is_weekday=True, is_holiday=False)
    assert gate.equity_session_open() is True
    _patch_mh(monkeypatch, is_regular_session=False, is_weekday=True, is_holiday=False)
    assert gate.equity_session_open() is False        # weekday but after-hours -> equity shut


def test_futures_gate_open_on_weekday_closed_on_weekend(monkeypatch):
    _patch_mh(monkeypatch, is_regular_session=False, is_weekday=True, is_holiday=False)
    assert gate.futures_fx_session_open() is True     # overnight weekday: futures/FX still trade
    _patch_mh(monkeypatch, is_regular_session=False, is_weekday=False, is_holiday=False)
    assert gate.futures_fx_session_open() is False    # weekend: hard closed
    _patch_mh(monkeypatch, is_regular_session=True, is_weekday=True, is_holiday=True)
    assert gate.futures_fx_session_open() is False    # holiday


def test_transactable_now_is_class_aware(monkeypatch):
    _patch_mh(monkeypatch, is_regular_session=False, is_weekday=True, is_holiday=False)
    assert gate.transactable_now("etf") is False       # equity shut after-hours
    assert gate.transactable_now("futures") is True     # futures still open
    assert gate.transactable_now("fx") is True


def test_gate_fails_closed_on_error(monkeypatch):
    def _boom():
        raise RuntimeError("market hours unavailable")
    monkeypatch.setattr(gate, "_market_status", _boom)
    assert gate.equity_session_open() is False
    assert gate.futures_fx_session_open() is False


# ---- applied in an equity shadow (ETF) ------------------------------------------------------------

def test_etf_shadow_defers_open_when_equity_shut(tmp_path, monkeypatch):
    from app.services.extended_etf_shadow_engine import ExtendedEtfShadowEngine as E
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "equity_session_open", lambda: False)
    m = E()
    monkeypatch.setattr(m, "enabled", lambda: True)
    monkeypatch.setattr(m, "_signal_targets", lambda: [{"symbol": "SPY", "trailing_return": 0.1}] * 4)
    monkeypatch.setattr(m, "_live_prices", lambda syms: {s.upper(): 100.0 for s in syms})
    m.STATE.mkdir(parents=True, exist_ok=True)
    out = m.mark()
    assert out["cohort_opened"] is False
    assert (not m.OPEN.exists()) or json.loads(m.OPEN.read_text()) == []


def test_etf_shadow_opens_when_equity_open(tmp_path, monkeypatch):
    from app.services.extended_etf_shadow_engine import ExtendedEtfShadowEngine as E
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "equity_session_open", lambda: True)
    m = E()
    monkeypatch.setattr(m, "enabled", lambda: True)
    monkeypatch.setattr(m, "_signal_targets",
                        lambda: [{"symbol": s, "trailing_return": 0.1} for s in ("SPY", "QQQ", "IWM")])
    monkeypatch.setattr(m, "_live_prices", lambda syms: {s.upper(): 100.0 for s in syms})
    m.STATE.mkdir(parents=True, exist_ok=True)
    out = m.mark()
    assert out["cohort_opened"] is True


# ---- applied in a futures shadow (weekday gate, NOT equity RTH) ------------------------------------

def test_futures_shadow_defers_open_on_weekend(tmp_path, monkeypatch):
    from app.services.futures_tsmom_shadow_engine import FuturesTsmomShadowEngine as F
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "futures_fx_session_open", lambda: False)
    m = F()
    monkeypatch.setattr(m, "enabled", lambda: True)
    picks = [{"symbol": f"S{i}", "ts_symbol": f"@S{i}", "side": "BUY"} for i in range(6)]
    monkeypatch.setattr(m, "_signal", lambda: picks)
    monkeypatch.setattr(m, "_live_prices", lambda syms: {s: 100.0 for s in syms})
    m.STATE.mkdir(parents=True, exist_ok=True)
    out = m.mark()
    assert out["cohort_opened"] is False


def test_futures_shadow_opens_on_weekday(tmp_path, monkeypatch):
    from app.services.futures_tsmom_shadow_engine import FuturesTsmomShadowEngine as F
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "futures_fx_session_open", lambda: True)
    m = F()
    monkeypatch.setattr(m, "enabled", lambda: True)
    picks = [{"symbol": f"S{i}", "ts_symbol": f"@S{i}", "side": "BUY"} for i in range(6)]
    monkeypatch.setattr(m, "_signal", lambda: picks)
    monkeypatch.setattr(m, "_live_prices", lambda syms: {s: 100.0 for s in syms})
    m.STATE.mkdir(parents=True, exist_ok=True)
    out = m.mark()
    assert out["cohort_opened"] is True
