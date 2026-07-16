import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_pnl_engine import PaperPnLEngine


# The MSTR incident: shorted at 99.00, price fell to 95.555. A short that falls is a WIN.
# Long-only math recorded it as -$34.45 and tripped a stop-loss on a profitable trade.

def test_winning_short_is_a_gain():
    out = PaperPnLEngine().calculate(entry_price=99.0, current_price=95.555,
                                     quantity=10, side="SELL")
    assert out["unrealized_pnl"] == 34.45      # was -34.45 under long-only math
    assert out["unrealized_pct"] > 0


def test_losing_short_is_a_loss():
    # Short squeezed: price rises against the short.
    out = PaperPnLEngine().calculate(entry_price=99.0, current_price=105.0,
                                     quantity=10, side="SELL")
    assert out["unrealized_pnl"] == -60.0
    assert out["unrealized_pct"] < 0


def test_long_math_unchanged():
    out = PaperPnLEngine().calculate(entry_price=100.0, current_price=110.0,
                                     quantity=5, side="BUY")
    assert out["unrealized_pnl"] == 50.0
    assert out["unrealized_pct"] == 10.0


def test_defaults_to_long_when_side_omitted():
    # Backward compatible with existing callers that pass no side.
    out = PaperPnLEngine().calculate(entry_price=100.0, current_price=90.0, quantity=1)
    assert out["unrealized_pnl"] == -10.0


def test_position_manager_direction_is_side_aware():
    # Guard the manager's own inline math (the code path that closed MSTR).
    import inspect

    from app.services import paper_position_manager_engine as M

    src = inspect.getsource(M.PaperPositionManagerEngine.manage_open_positions)
    assert "direction" in src, "position manager must compute P&L direction-aware"
    assert "* direction" in src
