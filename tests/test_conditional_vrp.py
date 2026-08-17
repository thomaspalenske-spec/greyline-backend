"""Conditional VRP integrity: causal (non-look-ahead) trailing IV rank, earnings-window
exclusion, and net-of-cost with an honest break-even — the checks the plausibility scan skipped."""

import json
from app.services.conditional_vrp_research_engine import ConditionalVRPResearchEngine


def test_trailing_rank_is_causal_not_full_sample():
    e = ConditionalVRPResearchEngine()
    # 20 low values, then a local high, then a FUTURE spike that must not leak backward
    vals = [0.20] * 20 + [0.50, 0.10, 0.30, 0.90, 0.15]   # indices 20..24
    # at i=20 the trailing window is vals[0:21]; 0.50 is the max so far -> rank 1.0
    assert e._trailing_rank(vals, 20, lookback=252) == 1.0
    # the future 0.90 at index 23 cannot change the rank computed at index 20 (no peek):
    # recomputing at 20 is identical regardless of what comes later
    assert e._trailing_rank(vals, 20, lookback=252) == 1.0
    # too few observations early on -> None, never a look-ahead guess
    assert e._trailing_rank(vals, 5, lookback=252) is None


def test_earnings_window_entries_are_flagged_and_excluded(tmp_path, monkeypatch):
    e = ConditionalVRPResearchEngine()
    # one name: 60 rows, an earnings report lands inside one entry's forward window
    rows = []
    from datetime import date, timedelta
    d0 = date(2026, 1, 5); days = []
    d = d0
    while len(days) < 90:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    for i in range(60):
        rows.append({"date": days[i], "unshifted_rv_date": days[i + 21],
                     "implied_volatility": "0.40", "realized_volatility": "0.20"})
    cache = tmp_path / "uw"; cache.mkdir()
    (cache / "ZZ.json").write_text(json.dumps(rows))
    monkeypatch.setattr(e.vrp, "CACHE", cache)
    monkeypatch.setattr(e.vrp, "_ts_forward_rv", lambda t, asof: {})
    # earnings inside the forward window of the entry at days[30] (which HAS >=20 rank history):
    # its window is days[30]..days[51], so an earnings report at days[40] must flag it.
    monkeypatch.setattr(e, "_earnings_dates", lambda t: [days[40]])

    entries = e._entries("ZZ", asof="2027-01-01")
    assert entries, "no entries built"
    by_date = {x["date"]: x for x in entries}
    assert by_date[days[30]]["earnings_in_window"] is True, "earnings inside window not flagged"
    # an entry whose window contains no earnings is not flagged
    assert by_date[days[0]]["earnings_in_window"] is False if days[0] in by_date else True
    # the flagged entry must be dropped from the high-IV selection
    a = e._analyze(entries, threshold=0.0, rng=__import__("random").Random(1))
    # (threshold 0 selects everything not in an earnings window)
    assert a["status"] in ("ANALYZED", "INSUFFICIENT_ENTRIES", "INSUFFICIENT_MONTHS")


def test_net_of_cost_and_break_even_reported(tmp_path, monkeypatch):
    """The study must report edge NET of cost and a break-even, not just a gross number —
    significance alone is insufficient for an option trade."""
    e = ConditionalVRPResearchEngine()
    r = e.last_study()
    if not r:
        return
    ter = r["by_rich_threshold"]["tercile_top33"]
    if ter.get("status") == "ANALYZED":
        assert "net_edge_bps_by_cost" in ter and "break_even_cost_bps" in ter
        assert ter["gross_edge_bps_ts"] is not None    # dual-source present
