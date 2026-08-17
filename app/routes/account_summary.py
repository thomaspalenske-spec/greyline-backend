import json
from datetime import datetime
from os import getenv
from pathlib import Path

from fastapi import APIRouter

from app.services.broker_account_view_engine import BrokerAccountViewEngine

router = APIRouter()

# LAST-KNOWN-GOOD cache: so a transient broker-read failure serves the last confirmed money figures
# (clearly labelled STALE + aged) instead of blanking every dashboard tile. This is not fantasy — it is
# the standard last-known-good pattern: live = unknown/degraded, alongside the last real reading and how
# old it is. The operator sees real (stale) numbers with an age badge, never a silent "—".
_LAST_GOOD = Path("app/data/state/account_summary_last_good.json")
_MONEY_KEYS = ("starting_capital", "deployed_capital", "deployed_pct_of_equity", "open_market_value",
               "tbill_sweep_value", "cash_on_hand", "buying_power", "unrealized_pnl", "realized_pnl",
               "total_equity", "total_return_pct", "return_24h_pct", "open_position_count")


def _save_last_good(resp):
    try:
        _LAST_GOOD.parent.mkdir(parents=True, exist_ok=True)
        _LAST_GOOD.write_text(json.dumps({"as_of": resp.get("timestamp"),
                                          **{k: resp.get(k) for k in _MONEY_KEYS}}))
    except Exception:
        pass


def _load_last_good():
    try:
        d = json.loads(_LAST_GOOD.read_text())
        try:
            d["age_seconds"] = round((datetime.utcnow()
                                      - datetime.fromisoformat(str(d.get("as_of")))).total_seconds())
        except Exception:
            d["age_seconds"] = None
        return d
    except Exception:
        return None


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

    # DEGRADED-READ GUARD: if the broker read FAILED this cycle, positions are UNKNOWN — not zero.
    # Without this, deployed/unrealized collapse to 0 and cash_on_hand=equity, publishing a fantasy
    # "0 positions, all cash" book (the same class the risk governor already guards). Publish
    # UNKNOWN (null) money tiles + a degraded flag so the dashboard can't render fantasy numbers.
    if not view.get("reads_ok", True):
        from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine
        try:
            realized = MissionRealizedPnlEngine().cumulative_realized()
        except Exception:
            realized = None
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account_mode": view.get("account_mode"), "account_label": view.get("account_label"),
            "reads_ok": False, "degraded": True,
            "starting_capital": round(base, 2), "realized_pnl": realized,
            "deployed_capital": None, "deployed_pct_of_equity": None, "open_market_value": None,
            "tbill_sweep_value": None, "cash_on_hand": None, "buying_power": None,
            "unrealized_pnl": None, "total_equity": None, "total_return_pct": None,
            "return_24h_pct": None,   # equity unknown this cycle -> don't record a bogus sample or fabricate a delta
            "open_position_count": None,
            # surface WHY the read failed so the operator (and diagnostics) see the real cause — a 429
            # throttle vs a broker-side 5xx vs a transient timeout are very different situations.
            "read_detail": view.get("read_detail"),
            "read_broker_side": view.get("read_broker_side"),
            "read_rate_limited": view.get("read_rate_limited"),
            # last confirmed reading (clearly aged) so the dashboard shows real stale numbers, not blank "—"
            "last_good": _load_last_good(),
            "status": "ACCOUNT_SUMMARY_BROKER_READ_DEGRADED",
        }

    # The T-bill sweep (SGOV) is a CASH-EQUIVALENT parking lot, not deployed risk capital — it is
    # ~0-duration Treasuries the sweep sells back on demand. Counting it as "deployed" overstates
    # risk and understates buying power: once the demand-driven sweep runs, deployed would jump to
    # ~74% and buying power drop to ~$2.5k with ZERO new risk taken. So split it out: DEPLOYED =
    # at-risk (non-SGOV) positions only; SGOV market value folds back into cash/buying-power.
    from app.services.tbill_cash_sweep_engine import TbillCashSweepEngine
    _tbill = TbillCashSweepEngine.symbol()

    def _is_tbill(r):
        return ((str(r.get("symbol") or "").split() or [""])[0]).upper() == _tbill

    at_risk = [r for r in rows if not _is_tbill(r)]
    cost_basis = round(sum(r["entry_price"] * r["quantity"] for r in at_risk), 2)          # deployed = at-risk only
    at_risk_market_value = round(sum(r["current_price"] * r["quantity"] for r in at_risk), 2)
    market_value = round(sum(r["current_price"] * r["quantity"] for r in rows), 2)          # all positions (for equity)
    tbill_value = round(sum(r["current_price"] * r["quantity"] for r in rows if _is_tbill(r)), 2)
    unrealized = round(sum(r["unrealized_pnl"] for r in rows), 2)

    # Mission-book equity = $10k base + CUMULATIVE realized (closed trades) + live unrealized. The
    # realized term is essential: without it a closed loss vanishes (the broker's daily realized
    # resets, so the legacy flatten's ~$4,100 loss snapped the equity back to $10k). Sourced from the
    # persistent mission realized ledger, not the broker's daily figure.
    from app.services.mission_realized_pnl_engine import MissionRealizedPnlEngine
    realized = MissionRealizedPnlEngine().cumulative_realized()
    mission_equity = round(base + realized + unrealized, 2)

    # Mission CASH = equity minus AT-RISK (non-SGOV) market value — so SGOV, being cash-equivalent,
    # counts toward cash/buying-power rather than being locked away as "deployed". The mission is
    # cash-funded with no margin, so buying power = cash on hand.
    cash_on_hand = round(mission_equity - at_risk_market_value, 2)

    # 24-HOUR RETURN: measured against the mission equity ~24h ago from a compact self-maintained history
    # (fed here on each healthy poll). None until ~24h of history exists — never a fabricated baseline.
    from app.services.account_return_horizon_engine import AccountReturnHorizonEngine
    horizon = AccountReturnHorizonEngine().record_and_measure(mission_equity)

    resp = {
        "timestamp": datetime.utcnow().isoformat(),
        "account_mode": view.get("account_mode"),
        "account_label": view.get("account_label"),
        "reads_ok": view.get("reads_ok"),

        # --- GreyLine mission book (the $10k GreyLine trades) ---
        "starting_capital": round(base, 2),
        "deployed_capital": cost_basis,
        "deployed_pct_of_equity": round(100 * cost_basis / mission_equity, 2) if mission_equity else 0,
        "open_market_value": market_value,
        "tbill_sweep_value": tbill_value,          # SGOV held (cash-equivalent, counted in cash below)
        "cash_on_hand": cash_on_hand,
        "buying_power": cash_on_hand,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "total_equity": mission_equity,
        "total_return_pct": round(100 * (mission_equity - base) / base, 2) if base else 0,
        "return_24h_pct": horizon.get("return_24h_pct"),   # None until ~24h of history has accumulated
        "return_24h": horizon,                             # baseline equity / as-of / samples / reason
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
    if view.get("reads_ok"):
        _save_last_good(resp)        # remember this good reading for the next degraded window
    return resp
