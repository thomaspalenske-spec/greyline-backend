"""Options capture must never silently lose a day — the panel is the ONLY evidence base an
options edge can be verified against, and a missed day cannot be reconstructed."""

import json

import pytest

from app.services.options_reality_capture_engine import OptionsRealityCaptureEngine


@pytest.fixture
def eng(tmp_path, monkeypatch):
    monkeypatch.setattr(OptionsRealityCaptureEngine, "OUT_DIR", tmp_path)
    return OptionsRealityCaptureEngine()


def _band(rows):
    return lambda self, max_cap=None: (rows, None) if max_cap is None else ([], None)


def test_captures_the_options_native_fields(eng, monkeypatch):
    rows = [{"ticker": "NVDA", "iv30d": "0.397", "iv_rank": 40.2,
             "realized_volatility": "0.3495", "variance_risk_premium": "0.0294",
             "implied_move_perc": "0.077", "gex_ratio": "0.565",
             "put_call_ratio": "0.504", "marketcap": 1e12}]
    monkeypatch.setattr(OptionsRealityCaptureEngine, "_band", _band(rows))
    r = eng.capture(day="2026-07-24")
    assert r["captured"] is True and r["rows"] == 1
    assert r["with_variance_risk_premium"] == 1
    rec = json.loads((eng.OUT_DIR / "options_surface_2026-07-24.jsonl").read_text().strip())
    # the fields the edge hypotheses actually need
    for k in ("variance_risk_premium", "iv30d", "iv_rank", "realized_volatility", "gex_ratio"):
        assert k in rec, f"{k} not captured"


def test_a_failed_capture_is_never_reported_as_success(eng, monkeypatch):
    """THE guarantee. If nothing came back, the day is a permanent hole — saying otherwise
    would silently corrupt the only evidence base the options mission has."""
    monkeypatch.setattr(OptionsRealityCaptureEngine, "_band", _band([]))
    r = eng.capture(day="2026-07-24")
    assert r["captured"] is False
    assert r["status"] == "CAPTURE_FAILED_NO_ROWS"
    assert "cannot be reconstructed" in r["detail"]
    assert not (eng.OUT_DIR / "options_surface_2026-07-24.jsonl").exists()


def test_capture_is_once_per_day_and_never_overwrites(eng, monkeypatch):
    rows = [{"ticker": "AAA", "iv30d": "0.3", "marketcap": 1e9}]
    monkeypatch.setattr(OptionsRealityCaptureEngine, "_band", _band(rows))
    assert eng.capture(day="2026-07-24")["captured"] is True
    again = eng.capture(day="2026-07-24")
    assert again["captured"] is False and again["status"] == "ALREADY_CAPTURED_TODAY"


def test_coverage_states_the_no_backtest_constraint(eng, monkeypatch):
    rows = [{"ticker": "AAA", "iv30d": "0.3", "marketcap": 1e9}]
    monkeypatch.setattr(OptionsRealityCaptureEngine, "_band", _band(rows))
    eng.capture(day="2026-07-24")
    cov = eng.coverage()
    assert cov["days_captured"] == 1 and cov["total_rows"] == 1
    assert "cannot be backtested" in cov["note"]
