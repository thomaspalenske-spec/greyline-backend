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
