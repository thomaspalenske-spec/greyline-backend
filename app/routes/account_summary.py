import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine

router = APIRouter()

OPTIONS_LEDGER = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")
STARTING_CAPITAL = 10000.0
STRATEGY_INTENT = "MOMENTUM_REVERSAL"


def _last(quote, symbol):
    try:
        r = quote.get_quote(symbol)
        return float(((r.get("response_json") or {}).get("Quotes") or [{}])[0].get("Last") or 0)
    except Exception:
        return 0.0


def _read(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


@router.get("/account-summary")
def account_summary():
    """The real account across BOTH books, with P&L attributed to its source.

    The dashboard's account cards read the options-only engine, so once the system
    moved to equity they showed $0 deployed and $0 unrealized while real stock was
    held — and reported a "Total Return" that belongs entirely to the RETIRED
    coin-flip options signal. Attribution matters: a loss the decommissioned system
    booked is not the live strategy's track record.
    """
    quote = TradeStationQuoteLiveEngine()
    equity_rows = PaperTradeLedgerEngine()._read_all()
    option_rows = _read(OPTIONS_LEDGER)

    realized_options = sum(float(r.get("realized_pnl") or 0)
                           for r in option_rows if r.get("status") == "CLOSED")
    realized_strategy = sum(float(r.get("realized_pnl") or 0) for r in equity_rows
                            if r.get("status") == "CLOSED" and r.get("trade_intent") == STRATEGY_INTENT)
    realized_other_equity = sum(float(r.get("realized_pnl") or 0) for r in equity_rows
                                if r.get("status") == "CLOSED" and r.get("trade_intent") != STRATEGY_INTENT)

    open_rows = [r for r in equity_rows if r.get("status") == "OPEN" and r.get("symbol")]
    cost_basis = unrealized = market_value = 0.0
    unrealized_strategy = 0.0
    for r in open_rows:
        entry = float(r.get("entry_price") or 0)
        qty = float(r.get("quantity") or 0)
        cur = _last(quote, r["symbol"]) or entry
        direction = -1 if str(r.get("side") or "").upper() in ("SELL", "SELL_SHORT", "SHORT") else 1
        pnl = (cur - entry) * qty * direction
        cost_basis += entry * qty
        market_value += cur * qty
        unrealized += pnl
        if r.get("trade_intent") == STRATEGY_INTENT:
            unrealized_strategy += pnl

    realized_total = realized_options + realized_strategy + realized_other_equity
    cash = STARTING_CAPITAL + realized_total - cost_basis
    total_equity = STARTING_CAPITAL + realized_total + unrealized
    strategy_pnl = realized_strategy + unrealized_strategy

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "starting_capital": STARTING_CAPITAL,
        "cash_on_hand": round(cash, 2),
        "buying_power": round(cash, 2),
        "deployed_capital": round(cost_basis, 2),
        "deployed_pct_of_equity": round(100 * cost_basis / total_equity, 2) if total_equity else 0,
        "open_market_value": round(market_value, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized_total, 2),
        "total_equity": round(total_equity, 2),
        "total_return_pct": round(100 * (total_equity - STARTING_CAPITAL) / STARTING_CAPITAL, 2),
        "open_position_count": len(open_rows),
        "closed_trade_count": len([r for r in equity_rows + option_rows if r.get("status") == "CLOSED"]),
        "total_trade_count": len([r for r in equity_rows + option_rows if r.get("symbol") or r.get("underlying")]),
        # Attribution — whose P&L is this, really?
        "attribution": {
            "retired_options_signal": round(realized_options, 2),
            "retired_equity_signal": round(realized_other_equity, 2),
            "momentum_reversal_realized": round(realized_strategy, 2),
            "momentum_reversal_unrealized": round(unrealized_strategy, 2),
            "momentum_reversal_total": round(strategy_pnl, 2),
            "note": ("Account return is dominated by the RETIRED coin-flip signal's losses. "
                     "momentum_reversal_total is the live strategy's own track record."),
        },
        "status": "ACCOUNT_SUMMARY_READY",
    }
