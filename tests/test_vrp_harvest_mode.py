"""The live VRP harvest is UNCONDITIONAL by default — the 24yr index backtest falsified rich-IV
conditioning. harvest_candidates() must include low-IV names that rich_iv_candidates() drops, while the
panel's rich_iv_candidates() stays rich-IV. Hermetic — vol series + earnings monkeypatched, no network."""

import pytest

from app.services.conditional_vrp_forward_panel_engine import ConditionalVRPForwardPanelEngine as P


def _rows(last_iv, base_iv):
    # 70 rows; every prior IV = base, last = last_iv -> controls the causal trailing rank of the latest obs
    rows = []
    for k in range(69):
        d = f"2024-{1 + k // 28:02d}-{1 + k % 28:02d}"
        rows.append({"date": d, "unshifted_rv_date": d, "implied_volatility": base_iv, "price": 100.0})
    rows.append({"date": "2024-04-01", "unshifted_rv_date": "2024-04-01",
                 "implied_volatility": last_iv, "price": 100.0})
    return rows


@pytest.fixture
def _panel(monkeypatch):
    series = {"HIGH": _rows(0.30, 0.10),   # latest IV is the series max -> rank ~1.0 (rich)
              "LOW": _rows(0.10, 0.30)}    # latest IV is the series min -> rank ~0.0 (cheap)
    monkeypatch.setattr(P, "_prefetch_series", lambda self, names, workers=8: None)
    monkeypatch.setattr(P, "_fresh_series", lambda self, t: series.get(t, []))
    p = P()
    monkeypatch.setattr(p.cvrp, "_earnings_dates", lambda t: [])
    return p


def test_rich_iv_gate_drops_the_cheap_name(_panel):
    got = {c["ticker"] for c in _panel.rich_iv_candidates(["HIGH", "LOW"])}
    assert got == {"HIGH"}                                  # cheap name gated out


def test_harvest_is_unconditional_by_default(monkeypatch, _panel):
    monkeypatch.delenv("GREYLINE_VRP_HARVEST_MODE", raising=False)
    got = {c["ticker"] for c in _panel.harvest_candidates(["HIGH", "LOW"])}
    assert got == {"HIGH", "LOW"}                           # BOTH harvested — no rich-IV gate
    # iv_rank still recorded for provenance
    ranks = {c["ticker"]: c["iv_rank"] for c in _panel.harvest_candidates(["HIGH", "LOW"])}
    assert ranks["HIGH"] > ranks["LOW"]


def test_harvest_mode_rich_iv_reverts_to_legacy_gate(monkeypatch, _panel):
    monkeypatch.setenv("GREYLINE_VRP_HARVEST_MODE", "rich_iv")
    got = {c["ticker"] for c in _panel.harvest_candidates(["HIGH", "LOW"])}
    assert got == {"HIGH"}                                  # explicit opt-in restores the (falsified) gate


def test_harvest_engine_uses_harvest_candidates():
    # the short-premium engine must call harvest_candidates (unconditional), not rich_iv_candidates
    import inspect
    from app.services import conditional_vrp_short_premium_engine as m
    src = inspect.getsource(m)
    assert "harvest_candidates(" in src and "rich_iv_candidates(" not in src
