"""Book-level greeks: the aggregate delta/vega/gamma/theta of the whole options book, and the
delta-neutral hedge. Sign convention is safety-critical — a short put is LONG delta."""

import json
from app.services.portfolio_greeks_engine import PortfolioGreeksEngine


def _engine(tmp_path, condor_legs):
    e = PortfolioGreeksEngine()
    e.VRP_LEDGER = tmp_path / "vrp.jsonl"
    e.OPT_LEDGER = tmp_path / "opt.jsonl"
    e.VRP_LEDGER.write_text(json.dumps({
        "symbol": "SPY", "quantity": 1, "status": "OPEN", "legs": condor_legs}) + "\n")
    return e


def _greeks(delta, gamma=0.01, vega=0.5, theta=-0.1):
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def test_short_put_is_long_delta_and_hedge_sells(tmp_path, monkeypatch):
    # a put-tilted condor: short 30d put (delta -0.30) + wing; short 15d call (+0.15) + wing
    legs = [
        {"symbol": "SPY 260828P600", "action": "SELLTOOPEN"},
        {"symbol": "SPY 260828P590", "action": "BUYTOOPEN"},
        {"symbol": "SPY 260828C660", "action": "SELLTOOPEN"},
        {"symbol": "SPY 260828C670", "action": "BUYTOOPEN"},
    ]
    e = _engine(tmp_path, legs)
    gmap = {
        "SPY 260828P600": _greeks(-0.30), "SPY 260828P590": _greeks(-0.10),
        "SPY 260828C660": _greeks(0.15), "SPY 260828C670": _greeks(0.05),
    }
    monkeypatch.setattr(e, "_chain_greeks", lambda u, x: gmap)
    monkeypatch.setattr(e, "_spot", lambda u: 640.0)
    bg = e.book_greeks()
    # short put (-0.30, sign -1) contributes +0.30 delta; net should be LONG (positive) from the tilt
    assert bg["net_delta_shares"] > 0, bg
    assert bg["delta_neutral"] is False
    assert bg["delta_hedge"]["action"] == "SELL"     # sell shares to neutralise a long-delta book


def test_flat_book_is_neutral(tmp_path, monkeypatch):
    e = PortfolioGreeksEngine()
    e.VRP_LEDGER = tmp_path / "v.jsonl"; e.OPT_LEDGER = tmp_path / "o.jsonl"
    bg = e.book_greeks()
    assert bg["open_legs"] == 0 and bg["delta_neutral"] is True


def test_net_vega_is_negative_for_short_premium(tmp_path, monkeypatch):
    """Selling premium = SHORT vega (net_vega < 0) — the actual size of the vol bet."""
    legs = [
        {"symbol": "SPY 260828P600", "action": "SELLTOOPEN"},
        {"symbol": "SPY 260828P590", "action": "BUYTOOPEN"},
    ]
    e = _engine(tmp_path, legs)
    gmap = {"SPY 260828P600": _greeks(-0.30, vega=0.80), "SPY 260828P590": _greeks(-0.10, vega=0.40)}
    monkeypatch.setattr(e, "_chain_greeks", lambda u, x: gmap)
    monkeypatch.setattr(e, "_spot", lambda u: 640.0)
    bg = e.book_greeks()
    # short the 0.80-vega put, long the 0.40-vega wing => net vega negative (short vol)
    assert bg["net_vega"] < 0


def test_hedge_gated_off_by_default(tmp_path, monkeypatch):
    legs = [{"symbol": "SPY 260828P600", "action": "SELLTOOPEN"}]
    e = _engine(tmp_path, legs)
    monkeypatch.setattr(e, "_chain_greeks", lambda u, x: {"SPY 260828P600": _greeks(-0.30)})
    monkeypatch.setattr(e, "_spot", lambda u: 640.0)
    r = e.hedge_delta(dry_run=True)
    assert r["status"] == "HEDGE_DRY_RUN" and "would" in r
