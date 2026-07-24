"""Phase 2 entry forecaster + learning loop:
- the limit price is bid + aggressiveness*(ask-bid), clamped to [bid, ask]
- the learning engine refines aggressiveness from real fill outcomes.
"""

import pytest

from app.services.options_entry_forecast_engine import OptionsEntryForecastEngine
from app.services.options_entry_learning_engine import OptionsEntryLearningEngine


# ---- forecaster math (pure) ----------------------------------------------

def test_forecast_spans_bid_to_ask():
    f = OptionsEntryForecastEngine()
    assert f.forecast(1.00, 2.00, aggressiveness=0.0)["limit_price"] == 1.00   # bid
    assert f.forecast(1.00, 2.00, aggressiveness=1.0)["limit_price"] == 2.00   # ask
    assert f.forecast(1.00, 2.00, aggressiveness=0.5)["limit_price"] == 1.50   # mid
    assert f.forecast(1.00, 2.00, aggressiveness=0.6)["limit_price"] == 1.60


def test_forecast_clamps_and_handles_one_sided():
    f = OptionsEntryForecastEngine()
    # clamp above ask / below bid
    assert f.forecast(1.00, 2.00, aggressiveness=1.5)["limit_price"] == 2.00
    assert f.forecast(1.00, 2.00, aggressiveness=-0.5)["limit_price"] == 1.00
    # one-sided quote -> marketable at the ask
    assert f.forecast(0, 2.00, aggressiveness=0.5)["limit_price"] == 2.00


# ---- learning loop (isolated to a temp dir) ------------------------------

@pytest.fixture
def learn(tmp_path, monkeypatch):
    monkeypatch.setattr(OptionsEntryLearningEngine, "DIR", tmp_path)
    monkeypatch.setattr(OptionsEntryLearningEngine, "PARAMS", tmp_path / "params.json")
    monkeypatch.setattr(OptionsEntryLearningEngine, "LEDGER", tmp_path / "outcomes.jsonl")
    return OptionsEntryLearningEngine()


def _seed(learn, n_filled, n_unfilled, fill_price=1.6):
    i = 0
    for _ in range(n_filled):
        oid = f"F{i}"; i += 1
        learn.record_forecast("X 260101C100", {"bid": 1.0, "ask": 2.0, "mid": 1.5,
                              "limit_price": 1.6, "aggressiveness": learn.aggressiveness()}, 1, oid)
        learn.resolve(oid, True, fill_price)
    for _ in range(n_unfilled):
        oid = f"U{i}"; i += 1
        learn.record_forecast("X 260101C100", {"bid": 1.0, "ask": 2.0, "mid": 1.5,
                              "limit_price": 1.2, "aggressiveness": learn.aggressiveness()}, 1, oid)
        learn.resolve(oid, False)


def test_default_aggressiveness(learn):
    assert learn.aggressiveness() == OptionsEntryLearningEngine.DEFAULT_AGGRESSIVENESS


def test_stats_fill_rate(learn):
    _seed(learn, n_filled=3, n_unfilled=7)
    s = learn.stats()
    assert s["resolved_samples"] == 10 and s["fill_rate"] == 0.3


def test_refine_raises_when_below_fill_floor(learn):
    _seed(learn, n_filled=3, n_unfilled=7)   # 30% fill < 55% floor -> must deploy, raise
    before = learn.aggressiveness()
    r = learn.refine()
    assert r["changed"] is True and r["reason"] == "BELOW_FILL_FLOOR_RAISED_TO_DEPLOY"
    assert learn.aggressiveness() == round(before + OptionsEntryLearningEngine.STEP, 3)


def test_refine_trims_cost_when_filling_well_but_paying_spread(learn):
    """THE FIX: 70% fill is fine, but filling at 1.6 on a 1.0/2.0 quote means paying 60% of the
    spread. With slack above the floor, the learner pulls back to capture a cheaper entry —
    optimising COST, not chasing an arbitrary fill target."""
    _seed(learn, n_filled=7, n_unfilled=3, fill_price=1.6)   # 70% fill, paid_frac 0.6
    before = learn.aggressiveness()
    r = learn.refine()
    assert r["reason"] == "TRIMMING_ENTRY_COST_WITHIN_FILL_FLOOR"
    assert r["avg_spread_paid_frac"] == 0.6
    assert learn.aggressiveness() == round(before - OptionsEntryLearningEngine.STEP, 3)


def test_refine_holds_when_fills_are_already_cheap(learn):
    """High fill rate but filling near the bid (paid_frac 0.05) -> nothing to save, hold."""
    _seed(learn, n_filled=8, n_unfilled=2, fill_price=1.05)  # 80% fill, paid_frac 0.05
    before = learn.aggressiveness()
    r = learn.refine()
    assert r["reason"] == "FILLS_ALREADY_CHEAP_NO_CHANGE"
    assert r["changed"] is False and learn.aggressiveness() == before


def test_refine_holds_near_the_fill_floor(learn):
    """Fill rate just above the floor (60%) -> don't risk a step that breaches it."""
    _seed(learn, n_filled=6, n_unfilled=4, fill_price=1.6)   # 60% fill, in [0.55, 0.65)
    before = learn.aggressiveness()
    r = learn.refine()
    assert r["reason"] == "NEAR_FILL_FLOOR_HOLDING"
    assert r["changed"] is False and learn.aggressiveness() == before


def test_refine_noop_without_enough_samples(learn):
    _seed(learn, n_filled=1, n_unfilled=1)
    r = learn.refine()
    assert r["changed"] is False and r["reason"] == "NOT_ENOUGH_SAMPLES"


def test_limit_price_lands_on_a_valid_option_increment():
    """TradeStation REJECTED our first live limit orders: "Price = 9.32 not rounded to a
    valid price increment [0.05]". Every forecast must sit on the $0.05 grid or it is a
    guaranteed reject, not a trade."""
    from app.services.options_entry_forecast_engine import OptionsEntryForecastEngine
    eng = OptionsEntryForecastEngine()
    # nickel-quoted classes (the ones that rejected us) MUST land on the 0.05 grid
    for bid, ask in ((9.20, 9.50), (5.15, 5.60), (0.35, 0.45), (12.10, 13.85)):
        limit = eng.forecast(bid, ask, aggressiveness=0.6)["limit_price"]
        assert abs(round(limit / 0.05) * 0.05 - limit) < 1e-9, f"{limit} off the 0.05 grid"
        assert bid <= limit <= ask
    # a penny-quoted class keeps penny precision instead of being needlessly coarsened
    fine = eng.forecast(1.02, 1.03, aggressiveness=0.6)["limit_price"]
    assert 1.02 <= fine <= 1.03
    assert abs(round(fine / 0.01) * 0.01 - fine) < 1e-9


def test_dead_broker_order_voids_the_ledger_entry(tmp_path, monkeypatch):
    """A rejected/cancelled limit order created NO position — leaving the entry OPEN is the
    exact phantom the Reality Guard caught in production."""
    import json
    from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine

    led = OptionsPaperTradeLedgerEngine()
    f = tmp_path / "options_paper_trade_ledger.jsonl"
    f.write_text(json.dumps({"option_symbol": "MRNA 260828C60", "status": "OPEN",
                             "contracts": 1}) + "\n"
                 + json.dumps({"option_symbol": "GLW 260828C180", "status": "OPEN",
                               "contracts": 1}) + "\n")
    monkeypatch.setattr(led, "ledger_file", f)

    out = led.void_unfilled("MRNA 260828C60", reason="BROKER_ORDER_REJECTED")
    assert out["voided"] == 1

    rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    by_sym = {r["option_symbol"]: r for r in rows}
    # voided, and NOT counted as a closed round-trip (no position ever existed)
    assert by_sym["MRNA 260828C60"]["status"] == "VOID_UNFILLED"
    assert by_sym["MRNA 260828C60"]["void_reason"] == "BROKER_ORDER_REJECTED"
    # the genuinely-held position is untouched
    assert by_sym["GLW 260828C180"]["status"] == "OPEN"


def _sweep_with(monkeypatch, tmp_path, snapshot, entries):
    """Drive sweep_phantoms against a fake broker snapshot and a temp ledger."""
    import json
    from app.services import options_entry_reconciler_engine as mod
    from app.services.broker_account_view_engine import BrokerAccountViewEngine
    from app.services.options_paper_trade_ledger_engine import OptionsPaperTradeLedgerEngine

    monkeypatch.setattr(BrokerAccountViewEngine, "snapshot", lambda self: snapshot)
    f = tmp_path / "led.jsonl"
    f.write_text("".join(json.dumps(e) + "\n" for e in entries))
    monkeypatch.setattr(OptionsPaperTradeLedgerEngine, "__init__", lambda self: None)
    monkeypatch.setattr(OptionsPaperTradeLedgerEngine, "ledger_file", f, raising=False)
    return mod.OptionsEntryReconcilerEngine.sweep_phantoms(
        mod.OptionsEntryReconcilerEngine.__new__(mod.OptionsEntryReconcilerEngine)), f


def test_sweep_voids_only_positions_the_broker_does_not_back(tmp_path, monkeypatch):
    import json
    old = "2026-01-01T00:00:00"
    snapshot = {"reads_ok": True,
                "positions": [{"symbol": "GLW 260828C180"}],      # really held
                "pending_buys": [{"symbol": "ALAB 260828C315"}]}  # order still working
    entries = [
        {"option_symbol": "GLW 260828C180", "status": "OPEN", "timestamp": old},
        {"option_symbol": "ALAB 260828C315", "status": "OPEN", "timestamp": old},
        {"option_symbol": "RKLB 260828C70", "status": "OPEN", "timestamp": old},  # phantom
    ]
    res, f = _sweep_with(monkeypatch, tmp_path, snapshot, entries)
    assert res["option_symbols"] == ["RKLB 260828C70"]

    rows = {json.loads(l)["option_symbol"]: json.loads(l)["status"]
            for l in f.read_text().splitlines() if l.strip()}
    assert rows["GLW 260828C180"] == "OPEN"       # held -> untouched
    assert rows["ALAB 260828C315"] == "OPEN"      # working order -> untouched
    assert rows["RKLB 260828C70"] == "VOID_UNFILLED"


def test_sweep_fails_closed_when_the_broker_read_is_degraded(tmp_path, monkeypatch):
    """"Broker doesn't show it" and "we couldn't ask" look identical — voiding a REAL
    position on a failed read would lose track of live risk. Void nothing."""
    import json
    entries = [{"option_symbol": "RKLB 260828C70", "status": "OPEN",
                "timestamp": "2026-01-01T00:00:00"}]
    res, f = _sweep_with(monkeypatch, tmp_path,
                         {"reads_ok": False, "status": "BROKER_ACCOUNT_READ_DEGRADED"}, entries)
    assert res["voided"] == 0
    assert res["status"] == "SWEEP_SKIPPED_BROKER_READ_DEGRADED"
    assert json.loads(f.read_text().splitlines()[0])["status"] == "OPEN"


def test_sweep_does_not_void_a_just_submitted_entry(tmp_path, monkeypatch):
    """A fill can beat the /positions read. Young entries get the benefit of the doubt."""
    from datetime import datetime
    entries = [{"option_symbol": "RKLB 260828C70", "status": "OPEN",
                "timestamp": datetime.utcnow().isoformat()}]
    res, _ = _sweep_with(monkeypatch, tmp_path,
                         {"reads_ok": True, "positions": [], "pending_buys": []}, entries)
    assert res["voided"] == 0
    assert res["skipped_too_recent"] == ["RKLB 260828C70"]
