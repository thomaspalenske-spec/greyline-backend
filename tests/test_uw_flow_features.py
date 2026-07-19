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
            {"call_premium_ask_side": 100.0, "put_premium_ask_side": 40.0, "net_premium": 20.0,
             "call_volume_ask_side": 30, "put_volume_ask_side": 10}],
        "historical_risk_reversal_skew": [
            {"date": "2026-07-16", "risk_reversal": "0.01"},   # older, ignored
            {"date": "2026-07-17", "risk_reversal": "0.05"}],   # latest
        "greek_exposure_by_strike": [
            {"date": "2026-07-17", "call_gex": "300", "put_gex": "-100",
             "call_delta": "5000", "put_delta": "-2000"}],
    })
    rec = UWFlowSignalEngine().extract(snap)
    assert rec["directional_flow"] == round((100 - 40) / 140, 4)
    assert rec["volume_flow"] == round((30 - 10) / 40, 4)   # ask-side VOLUME, distinct from premium
    assert rec["skew"] == 0.05            # latest date only
    assert rec["dealer_gex"] == 200.0     # 300 + (-100)
    assert rec["dealer_delta"] == 3000.0  # 5000 + (-2000)


def test_dark_pool_flow_classifies_by_nbbo_midpoint():
    eng = UWFlowSignalEngine()

    class FakeProvider:
        def dark_pool(self, symbol):
            return {"data": [
                {"price": "10.10", "nbbo_bid": "10.00", "nbbo_ask": "10.10", "premium": "300"},  # at ask -> buy
                {"price": "10.00", "nbbo_bid": "10.00", "nbbo_ask": "10.10", "premium": "100"},  # at bid -> sell
                {"price": "10.05", "nbbo_bid": "10.00", "nbbo_ask": "10.10", "premium": "999"},  # at mid -> neutral
                {"price": "10.10", "nbbo_bid": "10.00", "nbbo_ask": "10.10", "premium": "50",
                 "canceled": True},                                                              # canceled -> skip
            ]}
    eng._provider_instance = FakeProvider()
    assert eng._dark_pool_flow("TST") == round((300 - 100) / 400, 4)   # +0.5, mid + canceled excluded


def test_oi_flow_nets_call_vs_put_open_interest():
    eng = UWFlowSignalEngine()

    class FakeProvider:
        def oi_change(self, symbol):
            return {"data": [
                {"option_symbol": "TST260724C00330000", "oi_change": "300"},   # call +300
                {"option_symbol": "TST260724P00300000", "oi_change": "100"},   # put  +100
                {"option_symbol": "not-an-option", "oi_change": "9999"},        # unparseable -> skip
            ]}
    eng._provider_instance = FakeProvider()
    assert eng._oi_flow("TST") == round((300 - 100) / 400, 4)   # +0.5, net call-side OI build


def test_alert_flows_scope_sweeps_and_openings():
    eng = UWFlowSignalEngine()

    class FakeProvider:
        def flow_alerts(self, symbol):
            return {"data": [
                # sweeps: call ask 300 vs put ask 100 -> +0.5
                {"type": "call", "total_ask_side_prem": "300", "has_sweep": True, "volume_oi_ratio": "0.2"},
                {"type": "put", "total_ask_side_prem": "100", "has_sweep": True, "volume_oi_ratio": "0.1"},
                # non-sweep, non-opening -> ignored by both
                {"type": "put", "total_ask_side_prem": "9999", "has_sweep": False, "volume_oi_ratio": "0.3"},
                # opening via vol/OI>1: call 200 vs put 600 -> -0.5
                {"type": "call", "total_ask_side_prem": "200", "has_sweep": False, "volume_oi_ratio": "1.4"},
                {"type": "put", "total_ask_side_prem": "600", "has_sweep": False, "all_opening_trades": True},
            ]}
    eng._provider_instance = FakeProvider()
    sweep, opening = eng._alert_flows("TST")
    assert sweep == round((300 - 100) / 400, 4)     # +0.5 bullish sweeps
    assert opening == round((200 - 600) / 800, 4)   # -0.5 bearish opening (vol/OI + flag)


def test_alert_flows_none_when_subset_empty():
    eng = UWFlowSignalEngine()

    class FakeProvider:
        def flow_alerts(self, symbol):
            return {"data": [{"type": "call", "total_ask_side_prem": "100",
                              "has_sweep": False, "volume_oi_ratio": "0.2"}]}
    eng._provider_instance = FakeProvider()
    assert eng._alert_flows("TST") == (None, None)   # no sweeps, no openings


def test_provider_signals_are_best_effort():
    # A failing provider must never break recording — enrich just leaves them off.
    eng = UWFlowSignalEngine()

    class Boom:
        def dark_pool(self, s): raise RuntimeError("budget exhausted")
        def oi_change(self, s): raise RuntimeError("network down")
        def flow_alerts(self, s): raise RuntimeError("timeout")
    eng._provider_instance = Boom()
    rec = {"symbol": "TST"}
    eng._enrich(rec)
    assert "dark_pool_flow" not in rec and "oi_flow" not in rec
    assert "sweep_flow" not in rec and "opening_flow" not in rec


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
    # every feature is graded, including the newly added ones
    out = eng.grade()
    assert set(out["features"]) == {"directional_flow", "net_premium", "volume_flow", "skew",
                                    "dealer_gex", "dealer_delta", "dark_pool_flow", "oi_flow",
                                    "sweep_flow", "opening_flow"}
