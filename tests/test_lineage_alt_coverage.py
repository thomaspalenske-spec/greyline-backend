"""Price-bar lineage now guards BOTH stores — app/data/historical AND app/data/alt_assets (futures/FX) —
with dir-qualified keys so a symbol in both (C = Citigroup vs corn @C) can't collide. Hermetic."""

import json

from app.services.price_bar_lineage_engine import PriceBarLineageEngine as E


def _csv(p, closes):
    p.write_text("date,open,high,low,close,volume\n" + "\n".join(f"{d},1,1,1,{c},100" for d, c in closes) + "\n")


def test_bar_files_covers_both_stores_collision_safe(tmp_path, monkeypatch):
    hist = tmp_path / "hist"; alt = tmp_path / "alt"; hist.mkdir(); alt.mkdir()
    _csv(hist / "C_daily.csv", [("2020-01-02", 50.0)])     # Citigroup
    _csv(alt / "C_daily.csv", [("2020-01-02", 4.0)])       # corn @C — same filename, other store
    _csv(alt / "ES_daily.csv", [("2020-01-02", 3200.0)])
    monkeypatch.setattr(E, "HIST_DIR", hist)
    monkeypatch.setattr(E, "ALT_DIR", alt)
    keys = dict(E._bar_files())
    assert "C" in keys and "alt_assets/C" in keys and "alt_assets/ES" in keys
    assert keys["C"].parent == hist and keys["alt_assets/C"].parent == alt   # distinct files, no collision


def test_snapshot_manifest_includes_alt_assets(tmp_path, monkeypatch):
    hist = tmp_path / "hist"; alt = tmp_path / "alt"; hist.mkdir(); alt.mkdir()
    _csv(hist / "AAPL_daily.csv", [("2020-01-02", 75.0), ("2020-01-03", 76.0)])
    _csv(alt / "ES_daily.csv", [("2020-01-02", 3200.0), ("2020-01-03", 3210.0)])
    monkeypatch.setattr(E, "HIST_DIR", hist)
    monkeypatch.setattr(E, "ALT_DIR", alt)
    monkeypatch.setattr(E, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(E, "REPORT", tmp_path / "r.json")
    E().snapshot(force=True)
    m = json.loads((tmp_path / "m.json").read_text())
    assert "AAPL" in m["symbols"] and "alt_assets/ES" in m["symbols"]         # both stores baselined
