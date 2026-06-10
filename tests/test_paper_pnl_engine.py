import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper_pnl_engine import PaperPnLEngine


def test_paper_pnl_gain():
    result = PaperPnLEngine().calculate(
        entry_price=100.0,
        current_price=110.0,
        quantity=2
    )

    assert result["unrealized_pnl"] == 20.0
    assert result["unrealized_pct"] == 10.0
    assert result["status"] == "PAPER_PNL_CALCULATED"


def test_paper_pnl_loss():
    result = PaperPnLEngine().calculate(
        entry_price=100.0,
        current_price=90.0,
        quantity=2
    )

    assert result["unrealized_pnl"] == -20.0
    assert result["unrealized_pct"] == -10.0


def test_paper_pnl_zero_entry_price_safe():
    result = PaperPnLEngine().calculate(
        entry_price=0.0,
        current_price=100.0,
        quantity=1
    )

    assert result["unrealized_pct"] == 0
