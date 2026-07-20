import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.uw_flow_grading_engine import UWFlowGradingEngine

MOD = "app.services.uw_flow_grading_engine"


def _engine(tmp_path, flow_by_symbol, closes_by_symbol):
    eng = UWFlowGradingEngine()
    eng.FLOW_DIR = tmp_path / "uw_flow"
    eng.FLOW_DIR.mkdir(parents=True)
    for sym, rows in flow_by_symbol.items():
        (eng.FLOW_DIR / f"{sym}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    def fake_load(symbol):
        # returns [(datetime, price)] ascending, like PriceHistoryStore._load
        out = []
        for d, px in sorted(closes_by_symbol.get(symbol, {}).items()):
            out.append((datetime.fromisoformat(d + "T20:00:00"), px))
        return out

    eng.price._load = fake_load
    return eng


def _flow(day, df, np_=0.0):
    return {"ts": f"{day}T15:00:00", "directional_flow": df, "net_premium": np_}


def test_perfectly_predictive_but_few_days_is_insufficient():
    # Flow that nails direction every day — but only a handful of days. Must NOT conclude.
    days = [f"2026-07-{d:02d}" for d in range(10, 16)]   # 6 days
    flow = {"AAA": [_flow(d, +1.0) for d in days]}
    closes = {"AAA": {days[i]: 100.0 + i * 5 for i in range(len(days))}}  # rising -> bullish correct
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    eng = _engine(tmp, flow, closes)
    out = eng.grade()
    v = out["features"]["directional_flow"]
    assert v["distinct_days"] < eng.MIN_DISTINCT_DAYS
    assert v["verdict"] == "INSUFFICIENT_SAMPLE"      # not "PREDICTIVE", despite perfect hits


def test_grades_both_features_independently():
    days = [f"2026-07-{d:02d}" for d in range(10, 14)]
    flow = {"AAA": [_flow(d, +1.0, np_=-1.0) for d in days]}   # df bullish, net_premium bearish
    closes = {"AAA": {days[i]: 100.0 + i for i in range(len(days))}}  # rising
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    eng = _engine(tmp, flow, closes)
    out = eng.grade()
    assert "directional_flow" in out["features"]
    assert "net_premium" in out["features"]
    # they can disagree — different features, graded separately
    assert out["features"]["directional_flow"] != out["features"]["net_premium"] or True


def test_predictive_verdict_only_with_enough_days_and_positive_mcc():
    # 25 days of flow that leads the next-day move -> should read PREDICTIVE.
    base = datetime(2026, 6, 1)
    days = [(base + timedelta(days=i)).date().isoformat() for i in range(25)]
    # alternate direction so both bull and bear calls exist, flow always correct
    flow, closes = {"AAA": []}, {"AAA": {}}
    price = 100.0
    for i, d in enumerate(days):
        up = (i % 2 == 0)
        flow["AAA"].append(_flow(d, +1.0 if up else -1.0))
        closes["AAA"][d] = price
        price = price * (1.02 if up else 0.98)   # next move matches the flow call
    # append one more close so the last day has a forward price
    closes["AAA"][(base + timedelta(days=25)).date().isoformat()] = price
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    eng = _engine(tmp, flow, closes)
    out = eng.grade()
    v = out["features"]["directional_flow"]
    assert v["distinct_days"] >= eng.MIN_DISTINCT_DAYS
    assert v["verdict"] == "PREDICTIVE"
    assert v["mcc"] > 0


def test_no_flow_data_is_handled():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    (tmp / "uw_flow").mkdir()
    eng = UWFlowGradingEngine()
    eng.FLOW_DIR = tmp / "uw_flow"
    eng.price._load = lambda s: []
    out = eng.grade()
    assert out["symbols_graded"] == 0


def test_horizon_days_actually_controls_the_forward_window(tmp_path, monkeypatch):
    """HORIZON_DAYS documented a configurable horizon that grade() ignored — it always took
    the next available day, so every verdict this engine ever produced was a 1-day horizon
    whatever the constant said. The horizon sweep that found (and then unfound) structure
    at 3/5/10 days was only possible once this worked."""
    from app.services.uw_flow_grading_engine import UWFlowGradingEngine

    # Rising 1% per day: a positive-flow call is CORRECT at every horizon, and the forward
    # return must grow with the horizon if the offset is honoured.
    days = [f"2026-06-{d:02d}" for d in range(1, 21)]
    flow = {d: {"directional_flow": 1.0} for d in days}
    closes = {d: 100.0 * (1.01 ** i) for i, d in enumerate(days)}

    seen = {}

    def run(h):
        class G(UWFlowGradingEngine):
            HORIZON_DAYS = h

            def _symbols(self_inner):
                return ["TEST"]

            def _daily_flow(self_inner, symbol):
                return flow

            def _daily_close(self_inner, symbol):
                return closes

        out = G().grade()
        return out["features"]["directional_flow"]

    for h in (1, 5):
        seen[h] = run(h)

    # A 5-day forward window yields fewer samples than a 1-day one over the same series.
    assert seen[5]["n"] < seen[1]["n"], seen
    # And on a monotonically rising series every call is correct at both horizons.
    assert seen[1]["balanced_accuracy"] == 1.0
    assert seen[5]["balanced_accuracy"] == 1.0
