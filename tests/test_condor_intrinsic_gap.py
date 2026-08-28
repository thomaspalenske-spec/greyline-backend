"""Mid-life intrinsic-gap mark (RBLX case, 2026-08): when the underlying blows PAST a short strike, the ITM leg
goes unquotable in UW and _current_value fails closed to None — the loser must NOT hide as '—'. It's marked at
intrinsic. A spot still between the shorts is a transient quote gap and stays unpriced (never fabricated)."""

from app.services.condor_shadow_engine import CondorShadowEngine as C

_LEGS = {
    "short_call": {"symbol": "RBLX 260918C70", "strike": 70.0},
    "wing_call":  {"symbol": "RBLX 260918C72.5", "strike": 72.5},
    "short_put":  {"symbol": "RBLX 260918P42.5", "strike": 42.5},
    "wing_put":   {"symbol": "RBLX 260918P40", "strike": 40.0},
}   # put spread width 2.5, call spread width 2.5


def test_marks_intrinsic_when_blown_through_put_spread(monkeypatch):
    monkeypatch.setattr(C, "_underlying_spot", lambda self, sym: 39.18)   # below the WHOLE put spread
    cv = C()._intrinsic_mark_if_blown_through({"legs": _LEGS})
    assert cv == 2.5                                                       # put spread at max loss


def test_marks_intrinsic_when_blown_through_call_spread(monkeypatch):
    monkeypatch.setattr(C, "_underlying_spot", lambda self, sym: 80.0)    # above the WHOLE call spread
    assert C()._intrinsic_mark_if_blown_through({"legs": _LEGS}) == 2.5


def test_none_when_spot_still_between_the_shorts(monkeypatch):
    monkeypatch.setattr(C, "_underlying_spot", lambda self, sym: 55.0)    # inside 42.5..70 -> transient gap
    assert C()._intrinsic_mark_if_blown_through({"legs": _LEGS}) is None


def test_none_when_spot_unavailable(monkeypatch):
    monkeypatch.setattr(C, "_underlying_spot", lambda self, sym: None)
    assert C()._intrinsic_mark_if_blown_through({"legs": _LEGS}) is None
