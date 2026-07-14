import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.institutional.institutional_memory_engine import InstitutionalMemoryEngine
from app.services.live_universe_quote_scanner import LiveUniverseQuoteScanner
from app.services.price_history_store import PriceHistoryStore


def test_scanner_extracts_last_price():
    ext = LiveUniverseQuoteScanner._extract_last
    assert ext({"response_json": {"Quotes": [{"Last": "123.45"}]}}) == 123.45
    assert ext({"response_json": {"Quotes": [{"Last": 0}]}}) is None   # zero -> None
    assert ext({"response_json": {"Quotes": []}}) is None              # no quotes
    assert ext({"response_json": None}) is None                        # failed fetch
    assert ext({}) is None                                             # empty result


def test_price_accumulates_even_when_snapshot_dedups(tmp_path, monkeypatch):
    # Constant flow signal (buying=100/selling=0) makes snapshots dedup, but the price
    # series must keep growing so the fixed-horizon join has points near T and T+horizon.
    eng = InstitutionalMemoryEngine()
    eng.DATA_DIR = tmp_path / "mem"
    eng.DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = PriceHistoryStore(base_dir=str(tmp_path / "price_history"))
    monkeypatch.setattr(
        "app.services.price_history_store.PriceHistoryStore", lambda *a, **k: store
    )

    snap = {"symbol": "NVDA", "institutional_buying_score": 100.0, "institutional_selling_score": 0.0}
    r1 = eng.record("NVDA", snap, source="TEST", minimum_interval_seconds=0, price=181.10)
    r2 = eng.record("NVDA", snap, source="TEST", minimum_interval_seconds=0, price=182.25)

    assert r1["recorded"] is True
    assert r2["recorded"] is False and r2.get("reason") == "IDENTICAL_SNAPSHOT"
    pts = store._load("NVDA")
    assert len(pts) == 2, f"price should accumulate on dedup, got {len(pts)}"
    assert sorted(p[1] for p in pts) == [181.10, 182.25]


def test_snapshot_record_corecords_price_when_provided():
    eng = InstitutionalMemoryEngine()
    r = eng.record(
        "AAA",
        {"institutional_buying_score": 80, "institutional_selling_score": 20, "symbol": "AAA"},
        source="TEST",
        minimum_interval_seconds=0,
        price=123.45,
    )
    assert r["recorded"] is True

    cov = PriceHistoryStore().coverage("AAA")
    assert cov["points"] >= 1
    # the co-recorded price is retrievable near the snapshot time
    hit = PriceHistoryStore().price_at("AAA", cov["last"], max_tolerance_seconds=120)
    assert hit is not None and hit["price"] == 123.45


def test_price_corecord_failure_never_breaks_snapshot(monkeypatch):
    # If price co-recording raises, the snapshot must still record.
    import app.services.institutional.institutional_memory_engine as mod

    def boom(*a, **k):
        raise RuntimeError("price fetch down")

    monkeypatch.setattr(mod.InstitutionalMemoryEngine, "_co_record_price", staticmethod(boom))
    r = InstitutionalMemoryEngine().record(
        "BBB", {"x": 1, "symbol": "BBB"}, source="TEST", minimum_interval_seconds=0,
    )
    assert r["recorded"] is True  # snapshot survived the price failure
