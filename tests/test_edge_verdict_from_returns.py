"""The shared rigorous edge-verdict — the SAME small-sample-t 95% CI bar the live court uses, applied to
any cost-net return series so a zero-capital SHADOW is judged as strictly as a live sleeve (no soft
raw-Sharpe verdict luring a re-arm on a not-actually-significant edge)."""

from app.services.edge_persistence_engine import EdgePersistenceEngine as E


def test_too_few_is_accumulating():
    # below min_n the verdict is ACCUMULATING regardless of how the tiny-sample CI happens to fall
    # (the min-N gate overrides significance — the whole point of not trusting a thin sample)
    v = E.verdict_from_returns([0.01, 0.02, 0.01], min_n=8)
    assert v["n"] == 3 and v["verdict"].startswith("ACCUMULATING")


def test_empty_is_accumulating_zero():
    v = E.verdict_from_returns([], min_n=8)
    assert v["n"] == 0 and v["verdict"].startswith("ACCUMULATING") and v["significant"] is False


def test_consistent_winner_is_proven():
    # tight positive spread, n>=min_n -> CI clears 0 -> PROVEN (same logic as the live court)
    v = E.verdict_from_returns([0.009, 0.011] * 6, min_n=8)
    assert v["verdict"].startswith("PROVEN") and v["significant"] is True and v["ci95_pct"][0] > 0


def test_consistent_loser_is_decayed():
    v = E.verdict_from_returns([-0.009, -0.011] * 6, min_n=8)
    assert v["verdict"].startswith("DECAYED") and v["ci95_pct"][1] < 0


def test_noisy_zero_mean_is_unproven_not_proven():
    # big swings around ~0 -> CI spans 0 -> NOT significant (the false-confidence guard)
    v = E.verdict_from_returns([0.05, -0.05] * 8, min_n=8)
    assert v["verdict"].startswith("UNPROVEN") and v["significant"] is False


def test_action_floor_downgrades_trivial_edge():
    # significantly positive but tiny mean, with a floor -> UNPROVEN (below action floor)
    v = E.verdict_from_returns([0.0009, 0.0011] * 8, min_n=8, min_edge=0.005)
    assert v["verdict"].startswith("UNPROVEN") and "floor" in v["verdict"]


def test_shadows_surface_the_rigorous_verdict(monkeypatch, tmp_path):
    # each of the 3 wired shadows must expose rigorous_verdict from its report() (additive, non-breaking)
    from app.services.gex_mean_reversion_shadow_engine import GexMeanReversionShadowEngine as G
    from app.services.vanna_charm_shadow_engine import VannaCharmShadowEngine as V
    from app.services.momentum_reversal_shadow_engine import MomentumReversalShadowEngine as M
    for eng in (G, V, M):
        monkeypatch.setattr(eng, "CLOSED", tmp_path / f"{eng.__name__}.jsonl", raising=False)
    # no closed trades -> rigorous_verdict present and ACCUMULATING (not a soft 'no data' only)
    for Eng in (G, V, M):
        rep = Eng().report()
        assert "rigorous_verdict" in rep, f"{Eng.__name__} missing rigorous_verdict"
        rv = rep["rigorous_verdict"]
        assert rv is not None and rv["verdict"].startswith("ACCUMULATING")
