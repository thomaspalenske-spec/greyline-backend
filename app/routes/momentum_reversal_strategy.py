from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine
from app.services.momentum_reversal_rebalance_engine import MomentumReversalRebalanceEngine
from app.services.strategy_performance_engine import StrategyPerformanceEngine

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/strategy-performance")
def strategy_performance():
    """The strategy's forward track record: realized/unrealized P&L, equity curve, edge verdict."""
    return StrategyPerformanceEngine().evaluate()


@router.get("/strategy-dashboard", response_class=HTMLResponse)
async def strategy_dashboard(request: Request):
    """Live view of the momentum-reversal strategy: positions, P&L, targets, data health."""
    return templates.TemplateResponse("strategy_dashboard.html", {"request": request})


@router.get("/momentum-reversal-strategy")
def momentum_reversal_strategy(top_n: int = 5):
    """The rebuilt validated strategy's current target positions (dry run, no trades)."""
    return MomentumReversalStrategyEngine(top_n=top_n).run()


@router.get("/momentum-reversal-rebalance")
def momentum_reversal_rebalance(force: bool = False, top_n: int = 5):
    """Rebalance status; ?force=true realizes prior holdings and opens the current top-N now."""
    eng = MomentumReversalRebalanceEngine(top_n=top_n)
    return eng.rebalance(force=True) if force else eng.status()


@router.get("/momentum-reversal-positions")
def momentum_reversal_positions():
    """Open strategy positions marked to the latest close, with unrealized P&L."""
    from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine

    strat = MomentumReversalStrategyEngine()
    series, asof, source = strat.universe()
    last = {s: c[-1] for s, c in series.items() if c}

    open_pos = [t for t in PaperTradeLedgerEngine()._read_all()
                if t.get("status") == "OPEN" and t.get("trade_intent") == "MOMENTUM_REVERSAL"]
    rows, total_unreal, total_notional = [], 0.0, 0.0
    for t in open_pos:
        entry = float(t.get("entry_price") or 0)
        qty = float(t.get("quantity") or 0)
        cur = float(last.get(t.get("symbol"), entry) or entry)
        unreal = (cur - entry) * qty if t.get("side") == "BUY" else (entry - cur) * qty
        notional = abs(cur * qty)
        total_unreal += unreal
        total_notional += notional
        rows.append({
            "symbol": t.get("symbol"), "side": t.get("side"), "quantity": qty,
            "directional_bias": t.get("directional_bias"), "entry_price": round(entry, 2),
            "current_price": round(cur, 2), "notional": round(notional, 2),
            "unrealized_pnl": round(unreal, 2),
            "unrealized_pct": round(100 * unreal / (entry * qty), 2) if entry and qty else 0,
        })
    rows.sort(key=lambda r: r["unrealized_pnl"], reverse=True)
    return {
        "marked_as_of": asof, "data_source": source,
        "open_count": len(rows), "positions": rows,
        "total_unrealized_pnl": round(total_unreal, 2),
        "total_notional": round(total_notional, 2),
        "status": "MOMENTUM_REVERSAL_POSITIONS_READY",
    }
