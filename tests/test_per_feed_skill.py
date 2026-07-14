import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.per_feed_skill_engine import PerFeedSkillEngine
from app.services.price_history_store import PriceHistoryStore


def _setup(tmp_path):
    eng = PerFeedSkillEngine(horizon_hours=24, tolerance_hours=6, neutral_band=2.0)
    eng.ledger = tmp_path / "shadow.jsonl"
    eng.price_ledger = tmp_path / "prices.jsonl"
    eng.store = PriceHistoryStore(base_dir=tmp_path / "ph")
    return eng


def test_ranks_the_predictive_feed_first(tmp_path):
    eng = _setup(tmp_path)
    prices, shadow = [], []
    for i in range(40):
        sym = f"S{i}"
        up = i < 20
        prices.append({"symbol": sym, "snapshot_price": 100.0, "timestamp": "2026-07-01T10:00:00"})
        prices.append({"symbol": sym, "snapshot_price": (110.0 if up else 90.0), "timestamp": "2026-07-02T10:00:00"})
        shadow.append({
            "symbol": sym, "timestamp": "2026-07-01T10:00:00",
            # greek flow: perfectly predictive (bullish score when up, bearish when down)
            "greek_flow_score": 80 if up else 20,
            # momentum: always wrong
            "momentum_direction": "BEARISH" if up else "BULLISH",
            # flow buying: neutral direction not set
            "flow_direction": "NEUTRAL",
            # gamma: uninformative (constant 50 -> skipped)
            "spot_gamma_score": 50,
            "lit_flow_score": 50,
        })
    with open(eng.price_ledger, "w") as f:
        for r in prices:
            f.write(json.dumps(r) + "\n")
    with open(eng.ledger, "w") as f:
        for r in shadow:
            f.write(json.dumps(r) + "\n")

    r = eng.evaluate()
    assert r["joined_with_price"] == 40
    assert r["best_feed"] == "greek_flow"
    assert r["feeds"]["greek_flow"]["mcc"] == 1.0
    assert r["feeds"]["momentum_proxy"]["mcc"] == -1.0
    # neutral/constant feeds have no decisive calls -> insufficient, excluded from ranking
    assert r["feeds"]["spot_gamma_gex"]["verdict"] == "INSUFFICIENT_DATA"
    assert "greek_flow" in r["ranked_by_mcc"]
    assert r["ranked_by_mcc"].index("greek_flow") < r["ranked_by_mcc"].index("momentum_proxy")


def test_no_join_yet(tmp_path):
    eng = _setup(tmp_path)
    eng.ledger.write_text(json.dumps({"symbol": "AAA", "timestamp": "2026-07-01T10:00:00",
                                      "greek_flow_score": 80}) + "\n")
    eng.price_ledger.write_text("")
    r = eng.evaluate()
    assert r["joined_with_price"] == 0
    assert r["best_feed"] is None
