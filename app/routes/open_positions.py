import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine

router = APIRouter()

OPTIONS_LEDGER = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")


def _last(quote, symbol):
    try:
        r = quote.get_quote(symbol)
        return float(((r.get("response_json") or {}).get("Quotes") or [{}])[0].get("Last") or 0)
    except Exception:
        return 0.0


@router.get("/open-positions")
def open_positions():
    """Every open position across BOTH ledgers, marked to market.

    The operator dashboard's positions panel read only the options ledger, so once the
    system moved to equity it reported "No open positions" while real stock was held.
    This is the whole book — equity and options — so a position can't hide from the
    operator because it's in the wrong ledger.
    """
    quote = TradeStationQuoteLiveEngine()
    rows, total_pnl, total_notional = [], 0.0, 0.0

    # --- equity ---
    for t in PaperTradeLedgerEngine()._read_all():
        if t.get("status") != "OPEN" or not t.get("symbol"):
            continue
        entry = float(t.get("entry_price") or 0)
        qty = float(t.get("quantity") or 0)
        cur = _last(quote, t["symbol"]) or entry
        is_short = str(t.get("side") or "").upper() in ("SELL", "SELL_SHORT", "SHORT")
        direction = -1 if is_short else 1
        pnl = (cur - entry) * qty * direction
        pnl_pct = ((cur / entry - 1) * 100 * direction) if entry else 0.0
        total_pnl += pnl
        total_notional += abs(cur * qty)
        rows.append({
            "symbol": t["symbol"], "asset_type": "EQUITY",
            "side": "SHORT" if is_short else "LONG",
            "quantity": qty, "entry_price": round(entry, 2), "current_price": round(cur, 2),
            "unrealized_pnl": round(pnl, 2), "unrealized_pnl_pct": round(pnl_pct, 2),
            "status": "OPEN", "stage": t.get("trade_intent") or "—",
            "marked": "LIVE_QUOTE",
        })

    # --- options (legacy; the options path is retired, marked at entry) ---
    if OPTIONS_LEDGER.exists():
        for line in OPTIONS_LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line)
            except ValueError:
                continue
            if t.get("status") != "OPEN":
                continue
            entry = float(t.get("entry_price") or 0)
            contracts = float(t.get("contracts") or 0)
            notional = abs(entry * contracts * 100)
            total_notional += notional
            rows.append({
                "symbol": t.get("underlying") or t.get("symbol"), "asset_type": "OPTION",
                "side": "LONG", "quantity": contracts,
                "entry_price": round(entry, 2), "current_price": round(entry, 2),
                "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0,
                "status": "OPEN", "stage": t.get("option_symbol") or "OPTION",
                "marked": "ENTRY_NO_LIVE_MARK",
            })

    rows.sort(key=lambda r: r["unrealized_pnl"], reverse=True)
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "open_positions": rows,
        "open_count": len(rows),
        "equity_count": len([r for r in rows if r["asset_type"] == "EQUITY"]),
        "option_count": len([r for r in rows if r["asset_type"] == "OPTION"]),
        "total_unrealized_pnl": round(total_pnl, 2),
        "total_notional": round(total_notional, 2),
        "status": "OPEN_POSITIONS_READY",
    }
