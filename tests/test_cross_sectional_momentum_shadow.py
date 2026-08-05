"""XS-momentum shadow forward-test: hypothetical daily P&L, NO orders. Pure-math paths tested with
synthetic price arrays; no broker, no filesystem for the logic tests."""

from app.services.cross_sectional_momentum_shadow_engine import CrossSectionalMomentumShadowEngine as S


def test_selection_weights_top_n_equal_weight_with_absolute_filter():
    s = S()
    have = ["A", "B", "C", "D", "E"]
    i = S.LOOKBACK_DAYS + 5
    # build px so 12-1 momentum (px[i-SKIP]/px[i-LOOKBACK]-1) is: A +30%, B +20%, C +10%, D -5%, E +40%
    ratios = {"A": 1.30, "B": 1.20, "C": 1.10, "D": 0.95, "E": 1.40}
    px = {}
    for sym, r in ratios.items():
        arr = [100.0] * (i + 1)
        arr[i - S.LOOKBACK_DAYS] = 100.0      # 'old'
        arr[i - S.SKIP_DAYS] = 100.0 * r      # 'recent'
        px[sym] = arr
    w, moms = s._selection_weights(have, px, i)
    # TOP_N=4 of the POSITIVE ones, ranked: E(.40) A(.30) B(.20) C(.10); D filtered (negative)
    assert set(w.keys()) == {"E", "A", "B", "C"}
    assert "D" not in w
    assert all(abs(v - 0.25) < 1e-6 for v in w.values())     # equal weight 1/4


def test_all_negative_goes_to_cash():
    s = S()
    have = ["A", "B"]
    i = S.LOOKBACK_DAYS + 5
    px = {}
    for sym in have:
        arr = [100.0] * (i + 1)
        arr[i - S.LOOKBACK_DAYS] = 100.0
        arr[i - S.SKIP_DAYS] = 90.0           # -10% -> filtered
        px[sym] = arr
    w, _ = s._selection_weights(have, px, i)
    assert w == {}                            # nothing passes the absolute filter -> all cash


def test_disabled_marks_nothing(monkeypatch):
    monkeypatch.setenv("GREYLINE_XSMOM_SHADOW", "false")
    r = S().mark()
    assert r["status"] == "XSMOM_SHADOW_DISABLED" and r["acted"] is False


def test_report_no_data(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "LEDGER", tmp_path / "shadow_ledger.jsonl")
    r = S().report()
    assert r["days_tracked"] == 0 and "no marks yet" in r["verdict"]
