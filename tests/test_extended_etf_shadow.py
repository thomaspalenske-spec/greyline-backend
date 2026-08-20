"""Extended-ETF shadow: zero-capital cross-sectional-momentum forward-test on the new ETF universe. Ranks by
trailing return off the backfilled bars, holds top-K a week, settles at LIVE quotes, judged on the court's
bar. NO orders. Hermetic — universe/prices monkeypatched, no network."""

import csv
import json

import pytest

from app.services.extended_etf_shadow_engine import ExtendedEtfShadowEngine as X


@pytest.fixture(autouse=True)
def _force_session_open(monkeypatch):
    # Force the shadow-tradeability RTH gate OPEN so these open/settle tests are time-independent (the gate
    # itself is tested in test_shadow_tradeability_gate). Without this they fail whenever the suite runs after hours.
    monkeypatch.setattr("app.services.shadow_tradeability_gate.equity_session_open", lambda: True)


def test_signal_ranks_by_trailing_return_top_k(monkeypatch):
    monkeypatch.setattr(X, "_universe", lambda self: ["A", "B", "C", "D", "E", "F", "G"])
    tr = {"A": 0.10, "B": 0.50, "C": -0.20, "D": 0.30, "E": 0.05, "F": 0.40, "G": 0.20}
    monkeypatch.setattr(X, "_trailing_return", lambda self, s: tr[s])
    picks = [p["symbol"] for p in X()._signal_targets()]
    assert picks == ["B", "F", "D", "G", "A", "E"]                 # top-6 by trailing return, C dropped


def test_trailing_return_reads_bars(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "HIST", str(tmp_path))
    with open(tmp_path / "ZZ_daily.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "open", "high", "low", "close", "volume"])
        for i in range(70):
            w.writerow(["2026-01-%02d" % (i + 1), 0, 0, 0, 100 + i, 0])   # steadily rising
    assert X()._trailing_return("ZZ") > 0                          # 63d trailing return, positive
    # too-few bars -> None
    with open(tmp_path / "YY_daily.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "open", "high", "low", "close", "volume"])
        w.writerow(["2026-01-01", 0, 0, 0, 100, 0])
    assert X()._trailing_return("YY") is None


def test_mark_opens_non_overlapping_then_settles(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "STATE", tmp_path)
    monkeypatch.setattr(X, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(X, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(X, "_universe", lambda self: ["A", "B", "C", "D"])
    monkeypatch.setattr(X, "_trailing_return", lambda self, s: {"A": .4, "B": .3, "C": .2, "D": .1}[s])
    monkeypatch.setattr(X, "_live_prices", lambda self, syms: {str(s).upper(): 100.0 for s in syms})

    r1 = X().mark()
    assert r1["cohort_opened"] and r1["open_cohorts"] == 1
    r2 = X().mark()                                                # hold not elapsed -> no new cohort
    assert not r2["cohort_opened"] and r2["open_cohorts"] == 1

    # age the open cohort past its hold, then settle at +5%
    o = json.loads((tmp_path / "o.json").read_text())
    o[0]["opened"] = "2020-01-01"
    (tmp_path / "o.json").write_text(json.dumps(o))
    monkeypatch.setattr(X, "_live_prices", lambda self, syms: {str(s).upper(): 105.0 for s in syms})
    r3 = X().mark()
    assert r3["cohorts_closed"] == 1
    rec = json.loads((tmp_path / "c.jsonl").read_text().splitlines()[0])
    assert abs(rec["gross_return"] - 0.05) < 1e-6 and rec["net_return"] < rec["gross_return"]   # net of cost


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("GREYLINE_EXTENDED_ETF_SHADOW", "false")
    assert X().mark()["status"] == "ETF_SHADOW_DISABLED"


def test_report_accumulating_on_court_bar(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(X, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(X, "_universe", lambda self: [])
    monkeypatch.setattr(X, "_live_prices", lambda self, s: {})
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps({"net_return": 0.01}) for _ in range(3)) + "\n")
    rep = X().report()
    assert rep["cohorts_closed"] == 3 and "accumulating" in rep["verdict"].lower()
    assert rep["rigorous_verdict"]["verdict"].startswith("ACCUMULATING")   # court's min-N gate, same bar


def _isolate_all(monkeypatch, tmp_path):
    monkeypatch.setattr(X, "STATE", tmp_path)
    monkeypatch.setattr(X, "OPEN", tmp_path / "o.json")
    monkeypatch.setattr(X, "CLOSED", tmp_path / "c.jsonl")
    monkeypatch.setattr(X, "OPEN_LS", tmp_path / "ols.json")
    monkeypatch.setattr(X, "CLOSED_LS", tmp_path / "cls.jsonl")


def test_ls_opens_and_settles_as_market_neutral_spread(tmp_path, monkeypatch):
    """The long/short twin opens top-K long / bottom-K short and settles as a SPREAD (mean long − mean short),
    with cost charged on BOTH sleeves. Longs +10%, shorts −5% → gross spread 0.15, net 0.15 − 2*cost."""
    monkeypatch.setenv("GREYLINE_COST_BPS_ROUND_TRIP", "10")   # 0.001 round-trip
    _isolate_all(monkeypatch, tmp_path)
    uni = ["L%d" % i for i in range(6)] + ["S%d" % i for i in range(6)]
    tr = {**{"L%d" % i: 0.20 - i * 0.005 for i in range(6)},   # the 6 highest = long sleeve
          **{"S%d" % i: 0.06 - i * 0.005 for i in range(6)}}   # the 6 lowest = short sleeve
    monkeypatch.setattr(X, "_universe", lambda self: uni)
    monkeypatch.setattr(X, "_trailing_return", lambda self, s: tr[s])
    monkeypatch.setattr(X, "_live_prices", lambda self, syms: {str(s).upper(): 100.0 for s in syms})

    ls1 = X().mark()["long_short"]
    assert ls1["cohort_opened"] and ls1["open_cohorts"] == 1
    o = json.loads((tmp_path / "ols.json").read_text())
    sides = [l["side"] for l in o[0]["legs"]]
    assert sides.count("BUY") == 6 and sides.count("SELL") == 6

    o[0]["opened"] = "2020-01-01"                              # age past the weekly hold
    (tmp_path / "ols.json").write_text(json.dumps(o))
    monkeypatch.setattr(X, "_live_prices",
                        lambda self, syms: {str(s).upper(): (110.0 if str(s).upper().startswith("L") else 95.0)
                                            for s in syms})
    ls3 = X().mark()["long_short"]
    assert ls3["cohorts_closed"] == 1
    rec = json.loads((tmp_path / "cls.jsonl").read_text().splitlines()[0])
    assert abs(rec["gross_spread"] - 0.15) < 1e-6              # +0.10 long − (−0.05) short
    assert abs(rec["net_return"] - (0.15 - 2 * 0.001)) < 1e-6  # cost charged on BOTH sleeves
    assert rec["n_long"] == 6 and rec["n_short"] == 6


def test_ls_skipped_when_universe_too_small(tmp_path, monkeypatch):
    """Fewer than 2*TOP_K names can't form two disjoint sleeves — the L/S track opens nothing (long-only still runs)."""
    _isolate_all(monkeypatch, tmp_path)
    monkeypatch.setattr(X, "_universe", lambda self: ["A", "B", "C", "D"])
    monkeypatch.setattr(X, "_trailing_return", lambda self, s: {"A": .4, "B": .3, "C": .2, "D": .1}[s])
    monkeypatch.setattr(X, "_live_prices", lambda self, syms: {str(s).upper(): 100.0 for s in syms})
    out = X().mark()
    assert out["cohort_opened"]                                # long-only still opens
    assert out["long_short"]["open_cohorts"] == 0             # but no L/S cohort (too few names)
