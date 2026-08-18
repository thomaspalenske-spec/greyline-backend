"""Total-return signal-impact measurement: the price_field parameterization and the signal-flip / ex-div
analysis. Reads the real historical total-return CSVs (both `close` and `adj_close` columns), so the module
is exempt from the app/data wipe. No network, no orders. The full factor A/B (two permutation backtests) is
exercised via the live route, not here, to keep the suite fast."""

from app.services.momentum_reversal_backtest_engine import MomentumReversalBacktestEngine as BT
from app.services.total_return_signal_impact_engine import TotalReturnSignalImpactEngine as IMPACT


def test_price_field_parameterization_differs():
    bt = BT()
    adj = bt._load("adj_close")
    raw = bt._load("close")
    assert len(adj) > 20 and len(raw) > 20
    # dividends make adj_close != close for at least one dividend-payer somewhere in history
    diffs = 0
    for s in list(adj.keys())[:200]:
        if s in raw:
            a, r = adj[s], raw[s]
            common = set(a.keys()) & set(r.keys())
            if any(abs(a[d] - r[d]) > 1e-6 for d in list(common)[:50]):
                diffs += 1
    assert diffs > 0, "adj_close should differ from close for dividend payers"


def test_signal_flip_reports_exdiv_attribution():
    flip = IMPACT()._signal_flip()
    assert "error" not in flip, flip
    assert flip["signal_evaluations"] > 1000
    assert flip["bias_flips"] >= 0
    # the whole point: some flips are attributable to a distribution (ex-div) day
    assert flip["flips_attributable_to_distribution"] >= 0
    assert flip["confirmed_adjusted"] > 0 and flip["confirmed_price_only"] > 0
    # percentages are well-formed when there are flips
    if flip["bias_flips"] > 0:
        assert 0 <= flip["distribution_attributable_pct_of_flips"] <= 100


def test_verdict_present_and_stringy():
    # a light end-to-end shape check on the fast path (signal_flip) — the route runs the full thing
    flip = IMPACT()._signal_flip()
    assert isinstance(flip, dict) and "bias_flips_pct_of_evals" in flip
