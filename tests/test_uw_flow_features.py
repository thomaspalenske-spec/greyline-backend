import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.uw_flow_signal_engine import UWFlowSignalEngine
from app.services.uw_flow_grading_engine import UWFlowGradingEngine


def _snap(signals):
    return {"symbol": "TST", "timestamp": "2026-07-18T16:00:00Z",
            "providers": {"UNUSUAL_WHALES": {"signals": signals}}}


def test_extract_pulls_skew_gex_and_delta():
    snap = _snap({
        "flow_per_strike_intraday": [
            {"call_premium_ask_side": 100.0, "put_premium_ask_side": 40.0, "net_premium": 20.0}],
        "historical_risk_reversal_skew": [
            {"date": "2026-07-16", "risk_reversal": "0.01"},   # older, ignored
            {"date": "2026-07-17", "risk_reversal": "0.05"}],   # latest
        "greek_exposure_by_strike": [
            {"date": "2026-07-17", "call_gex": "300", "put_gex": "-100",
             "call_delta": "5000", "put_delta": "-2000"}],
    })
    rec = UWFlowSignalEngine().extract(snap)
    assert rec["directional_flow"] == round((100 - 40) / 140, 4)
    assert rec["skew"] == 0.05            # latest date only
    assert rec["dealer_gex"] == 200.0     # 300 + (-100)
    assert rec["dealer_delta"] == 3000.0  # 5000 + (-2000)


def test_extract_tolerates_missing_new_signals():
    # A snapshot with only options flow (no skew/greek) must still extract, with zeros.
    snap = _snap({"flow_per_strike_intraday": [
        {"call_premium_ask_side": 50.0, "put_premium_ask_side": 50.0, "net_premium": 0.0}]})
    rec = UWFlowSignalEngine().extract(snap)
    assert rec is not None
    assert rec["skew"] == 0.0 and rec["dealer_gex"] == 0.0 and rec["dealer_delta"] == 0.0


def test_grader_grades_all_features_and_skips_absent(tmp_path):
    eng = UWFlowGradingEngine()
    eng.FLOW_DIR = tmp_path
    import json
    # old record lacks the new features; new record has them. Both valid.
    old = {"ts": "2026-07-10T16:00:00Z", "directional_flow": 0.3, "net_premium": 10.0}
    new = {"ts": "2026-07-11T16:00:00Z", "directional_flow": 0.2, "net_premium": 5.0,
           "skew": 0.04, "dealer_gex": 100.0, "dealer_delta": 200.0}
    (tmp_path / "TST.jsonl").write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n")

    daily = eng._daily_flow("TST")
    assert daily["2026-07-10"]["skew"] is None       # absent -> None (grading skips it)
    assert daily["2026-07-11"]["skew"] == 0.04
    # all five features are graded
    out = eng.grade()
    assert set(out["features"]) == {"directional_flow", "net_premium", "skew",
                                    "dealer_gex", "dealer_delta"}
