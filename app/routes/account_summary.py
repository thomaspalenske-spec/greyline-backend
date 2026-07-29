from datetime import datetime
from os import getenv

from fastapi import APIRouter

from app.services.broker_account_view_engine import BrokerAccountViewEngine

router = APIRouter()


def _capital_base():
    try:
        return float(getenv("GREYLINE_ACCOUNT_CAPITAL_BASE", "10000") or 10000)
    except (TypeError, ValueError):
        return 10000.0


@router.get("/account-summary")
def account_summary():
    """Account summary sourced from the selected TradeStation account — not a local ledger.

    Two distinct, honestly-separated figures:
      * GreyLine MISSION BOOK — the capital GreyLine actually trades ($10k, the operator's
        set size). This is the headline; return % is measured against it.
      * The real TradeStation account it reads (paper SIM now, real money on flip). Its true
        equity/cash/buying-power are shown as-is — the SIM account is TradeStation-funded at
        $1,000,000; GreyLine deploys only the mission book from it. Nothing is faked to match.

    Open positions and unrealized P&L come from the broker, so the numbers reflect what is
    actually booked at TradeStation. When nothing is booked, this is a clean $10k / $0.
    """
    base = _capital_base()
    view = BrokerAccountViewEngine().snapshot()
    rows = view.get("positions", [])

    cost_basis = round(sum(r["entry_price"] * r["quantity"] for r in rows), 2)
    market_value = round(sum(r["current_price"] * r["quantity"] for r in rows), 2)
    unrealized = round(sum(r["unrealized_pnl"] for r in rows), 2)

    # Mission-book equity = $10k base + CUMULATIVE realized (closed trades) + live unrealized. The
    # realized term is essential: without it a closed loss vanishes (the broker's daily realized
    # resets, so the legacy flatten's ~$4,100 loss snapped the equity back to $10k). Sourced from the
    # persistent mission realized ledger, not the broker's daily figure.
    from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine
    realized = MissionRealizedPnlEngine().cumulative_realized()
    mission_equity = round(base + realized + unrealized, 2)

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "account_mode": view.get("account_mode"),
        "account_label": view.get("account_label"),
        "reads_ok": view.get("reads_ok"),

        # --- GreyLine mission book (the $10k GreyLine trades) ---
        "starting_capital": round(base, 2),
        "deployed_capital": cost_basis,
        "deployed_pct_of_equity": round(100 * cost_basis / mission_equity, 2) if mission_equity else 0,
        "open_market_value": market_value,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "total_equity": mission_equity,
        "total_return_pct": round(100 * (mission_equity - base) / base, 2) if base else 0,
        "open_position_count": len(rows),

        # --- the real TradeStation account being read (broker truth, not faked to $10k) ---
        "broker_account": {
            "mode": view.get("account_mode"),
            "label": view.get("account_label"),
            "host_kind": view.get("host_kind"),
            "equity": view.get("equity"),
            "cash_balance": view.get("cash_balance"),
            "buying_power": view.get("buying_power"),
            "working_orders": view.get("orders_working"),
            "note": ("GreyLine deploys only the $%s mission book from this account." % f"{base:,.0f}"),
        },
        "status": "ACCOUNT_SUMMARY_READY" if view.get("reads_ok") else "ACCOUNT_SUMMARY_BROKER_READ_DEGRADED",
    }
