"""T-bill sweep over-park fix (2026-09-10): the reserve must use the MORE CONSERVATIVE of the raw
MarketValue committed and the canonical BrokerAccountViewEngine at-risk value, so a short-option book
whose net MarketValue undercounts committed capital can't let the sweep park cash the book doesn't have
free (the negative-free-cash bug: $1,809 in SGOV while liquid cash was −$1,748)."""

from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine as T


def test_reserve_uses_conservative_max_with_canonical(monkeypatch):
    e = T()
    # raw MarketValue basis UNDERCOUNTS (short options net negative): says only $6,000 committed
    monkeypatch.setattr(e, "_non_sgov_position_value", lambda positions: 6000.0)
    # canonical dashboard at-risk says the real committed is $8,400
    monkeypatch.setattr(e, "_canonical_at_risk_value", lambda: 8400.0)
    monkeypatch.setattr(e, "_operating_buffer", lambda equity=None: 400.0)
    reserve = e._reserve(positions=[], equity=8500.0)
    # must reserve off the HIGHER committed (8400) + buffer, not the undercount (6000)
    assert reserve == 8800.0, reserve


def test_reserve_falls_back_to_raw_when_canonical_degraded(monkeypatch):
    e = T()
    monkeypatch.setattr(e, "_non_sgov_position_value", lambda positions: 6000.0)
    monkeypatch.setattr(e, "_canonical_at_risk_value", lambda: None)   # degraded read
    monkeypatch.setattr(e, "_operating_buffer", lambda equity=None: 400.0)
    reserve = e._reserve(positions=[], equity=8500.0)
    assert reserve == 6400.0, reserve   # old behavior preserved on degraded canonical read


def test_fix_never_lowers_reserve(monkeypatch):
    # canonical LOWER than raw -> max() keeps raw; the fix can only ever RAISE the reserve (fail-safe)
    e = T()
    monkeypatch.setattr(e, "_non_sgov_position_value", lambda positions: 7000.0)
    monkeypatch.setattr(e, "_canonical_at_risk_value", lambda: 5000.0)
    monkeypatch.setattr(e, "_operating_buffer", lambda equity=None: 0.0)
    assert e._reserve(positions=[], equity=9000.0) == 7000.0
