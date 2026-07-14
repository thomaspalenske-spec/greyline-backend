import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.decision_shadow_log_engine import DecisionShadowLogEngine
from app.services.shadow_comparison_engine import ShadowComparisonEngine
from app.services.price_history_store import PriceHistoryStore
from app.services.persistence.json_store import read_jsonl


def test_shadow_log_records_both_directions(tmp_path):
    eng = DecisionShadowLogEngine()
    eng.LEDGER = tmp_path / "shadow.jsonl"
    eng.log("NVDA", {"directional_bias": "BULLISH", "result": "EXECUTE"},
            {"institutional_buying_score": 80, "institutional_selling_score": 20})
    rows = read_jsonl(eng.LEDGER)
    assert len(rows) == 1
    assert rows[0]["momentum_direction"] == "BULLISH"
    assert rows[0]["flow_direction"] == "BULLISH"  # buying>selling


def test_shadow_log_flow_neutral_when_scores_equal(tmp_path):
    eng = DecisionShadowLogEngine()
    eng.LEDGER = tmp_path / "shadow.jsonl"
    eng.log("NVDA", {"directional_bias": "BEARISH"},
            {"institutional_buying_score": 50, "institutional_selling_score": 50})
    assert read_jsonl(eng.LEDGER)[0]["flow_direction"] == "NEUTRAL"


def _setup(tmp_path):
    eng = ShadowComparisonEngine(horizon_hours=24, tolerance_hours=6)
    eng.ledger = tmp_path / "shadow.jsonl"
    eng.price_ledger = tmp_path / "prices.jsonl"
    eng.store = PriceHistoryStore(base_dir=tmp_path / "ph")
    return eng


def test_flow_beats_momentum_head_to_head(tmp_path):
    eng = _setup(tmp_path)
    prices, shadow = [], []
    # 20 symbols go UP: flow says BULLISH (right), momentum says BEARISH (wrong)
    # 20 symbols go DOWN: flow says BEARISH (right), momentum says BULLISH (wrong)
    for i in range(40):
        sym = f"S{i}"
        up = i < 20
        p0, p1 = 100.0, (110.0 if up else 90.0)
        prices.append({"symbol": sym, "snapshot_price": p0, "timestamp": "2026-07-01T10:00:00"})
        prices.append({"symbol": sym, "snapshot_price": p1, "timestamp": "2026-07-02T10:00:00"})
        shadow.append({
            "symbol": sym, "timestamp": "2026-07-01T10:00:00",
            "momentum_direction": "BEARISH" if up else "BULLISH",   # always wrong
            "flow_direction": "BULLISH" if up else "BEARISH",        # always right
        })
    with open(eng.price_ledger, "w") as f:
        for r in prices:
            f.write(json.dumps(r) + "\n")
    with open(eng.ledger, "w") as f:
        for r in shadow:
            f.write(json.dumps(r) + "\n")

    result = eng.compare()
    assert result["joined_with_price"] == 40
    assert result["winner"] == "FLOW"
    assert result["institutional_flow"]["mcc"] > result["momentum_proxy"]["mcc"]


def test_no_join_yet_returns_none_winner(tmp_path):
    eng = _setup(tmp_path)
    eng.ledger.write_text(json.dumps({"symbol": "AAA", "timestamp": "2026-07-01T10:00:00",
                                      "momentum_direction": "BULLISH", "flow_direction": "BEARISH"}) + "\n")
    eng.price_ledger.write_text("")  # no prices
    r = eng.compare()
    assert r["joined_with_price"] == 0
    assert r["winner"] is None
