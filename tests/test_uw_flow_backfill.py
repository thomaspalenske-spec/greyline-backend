import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.uw_flow_backfill_engine import UWFlowBackfillEngine


class FakeProvider:
    """Records every path+params requested, and answers with the real response shapes."""

    OBSERVATION_ONLY_ENDPOINTS = {
        "flow_per_strike_intraday": "/api/stock/{ticker}/flow-per-strike-intraday",
        "greek_exposure_by_strike": "/api/stock/{ticker}/greek-exposure/strike",
        "historical_risk_reversal_skew": "/api/stock/{ticker}/historical-risk-reversal-skew",
    }

    def __init__(self):
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        if "flow-per-strike-intraday" in path:
            return {"data": [
                {"date": "2026-06-15", "call_premium_ask_side": 300.0,
                 "put_premium_ask_side": 100.0, "net_premium": 250.0,
                 "call_volume_ask_side": 30, "put_volume_ask_side": 10},
            ]}
        if "greek-exposure/strike" in path:
            return {"data": [{"date": "2026-06-15", "call_gex": 700.0, "put_gex": -200.0,
                              "call_delta": 50.0, "put_delta": -20.0}]}
        if "historical-risk-reversal-skew" in path:
            return {"data": [{"date": "2026-06-15", "risk_reversal": 0.04}]}
        if "darkpool" in path:
            return {"data": [{"price": 11.0, "nbbo_bid": 10.0, "nbbo_ask": 10.5,
                              "premium": 1000.0}]}          # above mid -> accumulation
        if "oi-change" in path:
            return {"data": [{"option_symbol": "AAPL260615C00150000", "oi_change": 500}]}
        return {"data": []}


def _engine():
    p = FakeProvider()
    return UWFlowBackfillEngine(provider=p), p


def test_builds_a_record_from_dated_calls_only():
    """Every component must describe the SAME historical day, or the record mixes dates."""
    eng, prov = _engine()
    rec = eng.build_record("AAPL", date(2026, 6, 15))
    assert rec is not None
    dated = [(p, q) for p, q in prov.calls if "date" in q]
    assert dated, "no dated calls were made"
    assert all(q["date"] == "2026-06-15" for _, q in dated), prov.calls


def test_timestamp_is_the_historical_day_not_now():
    """extract() stamps the record from the snapshot timestamp; if that were 'now', the
    grader would score June's flow against tonight's close."""
    eng, _ = _engine()
    rec = eng.build_record("AAPL", date(2026, 6, 15))
    assert rec["ts"].startswith("2026-06-15")


def test_uses_the_same_endpoints_as_the_live_snapshot():
    """/greek-exposure returns call_gamma while /greek-exposure/strike returns call_gex, so
    the wrong path yields dealer_gex = 0.0 silently rather than failing. Endpoints are read
    from the provider's own map precisely so the two paths cannot drift."""
    eng, prov = _engine()
    eng.build_record("AAPL", date(2026, 6, 15))
    paths = [p for p, _ in prov.calls]
    assert any("flow-per-strike-intraday" in p for p in paths)
    assert any("greek-exposure/strike" in p for p in paths)


def test_features_are_populated_not_zeroed():
    eng, _ = _engine()
    rec = eng.build_record("AAPL", date(2026, 6, 15))
    assert rec["directional_flow"] == 0.5          # (300-100)/400
    assert rec["net_premium"] == 250.0
    assert rec["dealer_gex"] == 500.0              # 700 + (-200)
    assert rec["dealer_delta"] == 30.0             # 50 + (-20)
    assert rec["dark_pool_flow"] == 1.0            # all prints above the mid
    assert rec["oi_flow"] == 1.0                   # call OI only


def test_never_calls_the_undated_enrichment():
    """_enrich() fetches dark pool/OI/alerts from UNDATED endpoints — today's data. On a
    record stamped June that is contamination that would look like predictive power."""
    eng, prov = _engine()
    eng.signal._enrich = lambda rec: (_ for _ in ()).throw(
        AssertionError("_enrich must never run during backfill"))
    eng.build_record("AAPL", date(2026, 6, 15))
    assert all("flow-alerts" not in p for p, _ in prov.calls)


def test_sweep_and_opening_are_absent_not_faked():
    """flow-alerts has no date parameter, so these cannot be reconstructed. The grader
    treats a missing feature as no observation; inventing them from undated alerts would
    be the contamination the engine exists to avoid."""
    eng, _ = _engine()
    rec = eng.build_record("AAPL", date(2026, 6, 15))
    assert "sweep_flow" not in rec
    assert "opening_flow" not in rec


def test_records_are_marked_as_backfill():
    eng, _ = _engine()
    assert eng.build_record("AAPL", date(2026, 6, 15))["source"] == "BACKFILL"


def test_backfill_skips_weekends_and_is_idempotent(tmp_path, monkeypatch):
    import app.services.uw_flow_backfill_engine as mod
    monkeypatch.setattr(mod, "OUT_DIR", tmp_path)
    eng, _ = _engine()

    first = eng.backfill(["AAPL"], days=5, end=date(2026, 6, 20))   # Sat 20th
    path = tmp_path / "AAPL.jsonl"
    written = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert first["written"] == len(written) == 5
    for rec in written:
        assert date.fromisoformat(rec["ts"][:10]).weekday() < 5     # no weekend rows

    second = eng.backfill(["AAPL"], days=5, end=date(2026, 6, 20))
    assert second["written"] == 0 and second["already_had"] == 5
    after = [l for l in path.read_text().splitlines() if l.strip()]
    assert len(after) == 5, "rerun duplicated records"
