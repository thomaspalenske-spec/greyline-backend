"""Per-condor cap SENSITIVITY diagnostic — the risk-vs-breadth decision tool. For each earnings candidate
it builds the TIGHTEST defined-risk condor (unbounded cap) off the chain, then counts how many are
tradeable at each cap level. Proves: the current cap correctly gates by single-position risk, raising it
admits more names only by taking more % equity, and structurally-untradeable names aren't unlocked by it."""

from app.services.earnings_vol_harvest_engine import EarningsVolHarvestEngine as E
import app.services.conditional_vrp_short_premium_engine as vrp_mod


def _prep(monkeypatch, per_name, equity=10000.0, current_cap=500.0):
    # candidates
    monkeypatch.setattr(E, "_candidates",
                        lambda self, today=None: [{"ticker": t, "report_date": "2026-08-03"} for t in per_name])
    monkeypatch.setattr(E, "_expiry_after", lambda self, t, rd: "2026-08-07")
    monkeypatch.setattr(E, "_chain_snapshot", lambda self, t, exp, uw=None, ts=None: {"contracts": ["x"]})
    # build_condor returns each name's tightest structure (or a skip) keyed by ticker
    def _build(self, symbol, contracts, put_delta=None, call_delta=None, max_loss_cap=None):
        spec = per_name[symbol]
        if spec.get("skip"):
            return {"skip": spec["skip"]}
        mlp = spec["min_max_loss"]
        return {"symbol": symbol, "max_loss_per_condor": mlp, "credit_per_condor": spec.get("credit", 1.0),
                "return_on_risk": round((spec.get("credit", 1.0) * 100) / mlp, 3)}
    monkeypatch.setattr(vrp_mod.ConditionalVRPShortPremiumEngine, "build_condor", _build)
    # equity + cap
    import app.services.sleeve_capital_budget_engine as scb
    monkeypatch.setattr(scb.SleeveCapitalBudgetEngine, "_live", classmethod(lambda cls: (equity, equity)))
    monkeypatch.setattr(scb.SleeveCapitalBudgetEngine, "per_condor_max_loss", classmethod(lambda cls: current_cap))


def test_sweep_counts_tradeable_by_cap(monkeypatch):
    # OKE cheap ($440), AXON/STRL wide ($1000/$1500), LSCC skips structurally (thin credit)
    _prep(monkeypatch, {
        "OKE": {"min_max_loss": 440.0}, "AXON": {"min_max_loss": 1000.0},
        "STRL": {"min_max_loss": 1500.0}, "LSCC": {"skip": "credit 0.1 below floor"}})
    r = E().cap_sensitivity(caps=[500.0, 1000.0, 1500.0])
    assert r["current_cap_usd"] == 500.0 and r["current_cap_pct_of_equity"] == 5.0
    assert r["tradeable_now"] == ["OKE"] and r["tradeable_now_count"] == 1
    sweep = {s["cap_usd"]: s for s in r["cap_sweep"]}
    assert sweep[500.0]["tradeable"] == ["OKE"]
    assert sweep[1000.0]["tradeable"] == ["AXON", "OKE"]                 # +AXON at 10% equity
    assert sweep[1500.0]["tradeable"] == ["AXON", "OKE", "STRL"]         # +STRL at 15% equity
    assert sweep[1000.0]["cap_pct_of_equity"] == 10.0


def test_structurally_untradeable_not_unlocked_by_cap(monkeypatch):
    # LSCC skips even at the unbounded cap -> reported separately, never appears in the sweep
    _prep(monkeypatch, {"OKE": {"min_max_loss": 440.0}, "LSCC": {"skip": "credit below floor"}})
    r = E().cap_sensitivity(caps=[500.0, 5000.0])
    unt = [u["ticker"] for u in r["structurally_untradeable"]]
    assert "LSCC" in unt
    for s in r["cap_sweep"]:
        assert "LSCC" not in s["tradeable"]                             # a bigger cap can't unlock it


def test_pct_of_equity_reported_per_name(monkeypatch):
    _prep(monkeypatch, {"OKE": {"min_max_loss": 440.0}}, equity=10000.0)
    r = E().cap_sensitivity(caps=[500.0])
    n = r["names"][0]
    assert n["ticker"] == "OKE" and n["pct_of_equity"] == 4.4 and n["tradeable_at_current_cap"] is True


def test_default_caps_scale_from_current(monkeypatch):
    _prep(monkeypatch, {"OKE": {"min_max_loss": 440.0}}, current_cap=500.0)
    r = E().cap_sensitivity()                                           # no caps -> 1x/1.5x/2x/3x current
    caps = sorted(s["cap_usd"] for s in r["cap_sweep"])
    assert caps == [500.0, 750.0, 1000.0, 1500.0]


def test_verdict_names_the_tradeoff(monkeypatch):
    _prep(monkeypatch, {"OKE": {"min_max_loss": 440.0}, "AXON": {"min_max_loss": 1000.0}})
    r = E().cap_sensitivity(caps=[500.0])
    assert "UNPROVEN edge" in r["verdict"] and "GREYLINE_CONDOR_MAX_LOSS_PCT" in r["verdict"]
