import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from app.services.broker_account_view_engine import BrokerAccountViewEngine

router = APIRouter()

OPTIONS_LEDGER = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")


def _greyline_managed_symbols():
    """Ask the engine which symbols GreyLine is managing — display-only labelling.

    The route deliberately does NOT read a ledger itself: positions must come from the
    broker, never the local paper ledger (a source-text guard enforces this, because
    sourcing holdings from the ledger is exactly how the fake book happened).
    """
    try:
        from app.services.greyline_reality_guard_engine import GreyLineRealityGuardEngine
        return GreyLineRealityGuardEngine().managed_symbols()
    except Exception:
        return set()


def _doctrine_levels():
    """The exit doctrine's REAL trigger levels per open option, keyed by option symbol.

    The doctrine fires on the UNDERLYING's move (2.5-ATR stop; TP1/2/3 at 1.5/3/4.5 ATR;
    runner), so the levels shown must be underlying prices — not the option premium. Read
    from the ledger (GreyLine's own decision record) purely to DISPLAY; what's actually held
    still comes from the broker, so this can't resurrect a phantom position.
    """
    levels = {}
    if not OPTIONS_LEDGER.exists():
        return levels
    try:
        for line in OPTIONS_LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            t = json.loads(line)
            if t.get("status") != "OPEN" or not t.get("option_symbol"):
                continue
            ed = t.get("exit_doctrine_underlying") or {}
            st = t.get("doctrine_state_u") or {}
            if not ed:
                continue
            stop = t.get("current_stop_underlying")
            if stop is None:
                stop = ed.get("initial_stop")
            levels[t["option_symbol"]] = {
                "stop_loss": round(float(stop), 2) if stop is not None else None,
                "targets": [round(float(x), 2) for x in (ed.get("targets") or [])],
                "tps_filled": st.get("targets_filled"),
                "underlying": t.get("underlying"),
                "underlying_price": t.get("underlying_current_price"),
                "underlying_entry_price": t.get("underlying_entry_price"),
                "runner_contracts": ed.get("contracts_runner"),
                "levels_basis": "UNDERLYING",
            }
    except Exception:
        pass
    return levels


@router.get("/open-positions")
def open_positions():
    """Open positions read STRAIGHT from the selected TradeStation account.

    Source is the one account selector (paper SIM now, real money when the operator flips
    GREYLINE_DASHBOARD_ACCOUNT_MODE=live) — never the local paper ledger for WHAT is held.
    Option rows are then enriched with the exit doctrine's real underlying stop/TP levels for
    display, so the Stop/Take-Profit columns show what actually fires.
    """
    view = BrokerAccountViewEngine().snapshot()
    rows = view.get("positions", [])
    doctrine = _doctrine_levels()
    managed = _greyline_managed_symbols()
    # Symbols with a working SELLTOCLOSE — being liquidated right now (e.g. an account reset
    # placed the closes, which fill at the next open). These must read as CLOSING, not as
    # orphaned UNMANAGED risk that nobody is acting on.
    closing = {str(c.get("symbol") or "").upper(): c for c in (view.get("pending_closes") or [])}
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        # Total initial cost in real dollars (option premium x100 x contracts) — computed for
        # EVERY row up front, before any status branch, so a closing/unmanaged row still shows
        # its cost. (A stray `continue` here once blanked the Cost column on closing rows.)
        mult = 100 if r.get("asset_type") == "OPTION" else 1
        r["initial_cost"] = round(float(r.get("entry_price") or 0) * mult * abs(float(r.get("quantity") or 0)), 2)
        r["limit_buy"] = None                # filled at market — nothing pending
        r["pending"] = False
        # The account can hold positions GreyLine did NOT open (a stray fill, a manual trade).
        # They carry no stop, no take-profit and no maturity rule, so rendering them like the
        # rest of the book overstates what GreyLine is actually controlling. Mark them.
        r["managed_by_greyline"] = sym in managed
        if sym in closing:
            lim = closing[sym].get("limit_price")
            r["status"] = "CLOSING"
            r["stage"] = (f"SELLTOCLOSE @ ${lim} queued · fills at open" if lim
                          else "close order queued · fills at open")
            r["stop_loss"], r["targets"], r["tps_filled"] = None, [], None
            continue
        if not r["managed_by_greyline"]:
            r["status"] = "UNMANAGED"
            r["stage"] = "not opened by GreyLine · no stop/TP applies"
        if r.get("asset_type") == "OPTION":
            d = doctrine.get(r.get("symbol"))
            if d:
                r["stop_loss"] = d["stop_loss"]
                r["targets"] = d["targets"]
                r["tps_filled"] = d["tps_filled"]
                r["underlying"] = d["underlying"]
                r["underlying_price"] = d["underlying_price"]
                r["underlying_entry_price"] = d["underlying_entry_price"]
                r["runner_contracts"] = d["runner_contracts"]
                r["levels_basis"] = "UNDERLYING"

    # Pending limit BUYs we're waiting to fill — shown as PENDING rows (not positions yet).
    for pb in view.get("pending_buys", []):
        mult = 100 if pb.get("asset_type") == "OPTION" else 1
        limit = pb.get("limit_price")
        rows.append({
            "symbol": pb.get("symbol"), "asset_type": pb.get("asset_type"),
            "side": "LONG", "quantity": pb.get("quantity"), "shares": pb.get("quantity"),
            "entry_price": None, "current_price": None,
            "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0,
            "stop_loss": None, "targets": [], "tps_filled": None,
            "limit_buy": limit, "pending": True,
            "initial_cost": round(float(limit or 0) * mult * abs(float(pb.get("quantity") or 0)), 2),
            "status": "PENDING", "stage": f"waiting · limit ${limit}" if limit else "waiting",
        })

    total_pnl = round(sum(r.get("unrealized_pnl") or 0 for r in rows), 2)
    total_notional = round(sum(abs((r.get("current_price") or 0) * (r.get("quantity") or 0)) for r in rows), 2)
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "account_mode": view.get("account_mode"),
        "account_label": view.get("account_label"),
        "reads_ok": view.get("reads_ok"),
        "open_positions": rows,
        "open_count": len(rows),
        "equity_count": len([r for r in rows if r.get("asset_type") != "OPTION"]),
        "option_count": len([r for r in rows if r.get("asset_type") == "OPTION"]),
        "total_unrealized_pnl": total_pnl,
        "total_notional": total_notional,
        "status": "OPEN_POSITIONS_READY" if view.get("reads_ok") else "OPEN_POSITIONS_BROKER_READ_DEGRADED",
    }
