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


_TREND_BASKET = {"QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"}


def _dynamic_exit(sym, current_price):
    """The sleeve's REAL, dynamic exit — not the 35% disaster backstop. Trend exits on a 200-DMA
    break (confirmed reversal); carry on backwardation; T-bill is a cash floor."""
    base = str(sym or "").split()[0].upper()
    try:
        if base in _TREND_BASKET:
            from app.services.trend_following_engine import TrendFollowingEngine
            sig = TrendFollowingEngine()._signal(base, float(current_price or 0))
            if sig and sig.get("sma"):
                sma = round(sig["sma"], 2)
                above = round((sig["last"] / sig["sma"] - 1) * 100, 1)
                return {"stop_loss": sma,
                        "stage": f"trend exit: sell on a close below the 200-DMA ${sma} ({above}% above now)",
                        "tp_note": "rides the trend · full exit on 200-DMA break (no partial TP)"}
        if base == "SVXY":
            from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
            from app.services.vol_term_structure_carry_engine import VolTermStructureCarryEngine
            s = VolTermStructureCarryEngine().signal(TradeStationQuoteLiveEngine())
            if s.get("ok"):
                cond = "contango · hold" if s.get("contango") else "BACKWARDATION · exiting"
                return {"stop_loss": None,
                        "stage": f"carry exit: sell on backwardation (VIX>VIX3M) · now {s['vix']}/{s['vix3m']} = {cond}",
                        "tp_note": "harvests the roll until the curve inverts (no fixed TP)"}
        if base == "SGOV":
            return {"stop_loss": None, "stage": "cash floor · no exit stop", "tp_note": "cash equivalent"}
    except Exception:
        pass
    return None


def _vrp_condor_levels():
    """Per-leg-symbol -> the condor's unit stop/profit-take, for display. Read from the engine (not
    a ledger here) so the 'positions come from the broker, never the local ledger' rule holds."""
    try:
        from app.services.conditional_vrp_short_premium_engine import ConditionalVRPShortPremiumEngine
        return ConditionalVRPShortPremiumEngine().condor_display_levels()
    except Exception:
        return {}


def _underlying_prices(option_symbols):
    """{underlying: last_price} for the distinct underlyings of these option symbols. Best-effort
    live quotes, fetched ONCE per distinct underlying (IWM, LQD, ...) — display only, so a slow or
    failed quote just leaves the price blank rather than breaking the row."""
    unders = {str(s).split()[0].upper() for s in option_symbols if s and " " in str(s)}
    out = {}
    if not unders:
        return out
    try:
        from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
        q = TradeStationQuoteLiveEngine()
        for u in unders:
            try:
                rj = (q.get_quote(u).get("response_json") or {})
                row = (rj.get("Quotes") or [rj])[0] if isinstance(rj, dict) else {}
                px = row.get("Last") or row.get("Close")
                if px:
                    out[u] = float(px)
            except Exception:
                pass
    except Exception:
        pass
    return out


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
    condor_levels = _vrp_condor_levels()
    # Underlying spot for every option leg, so a row shows equity price -> premium -> total contract
    # (the operator wants to trace the math end-to-end). Deduped: one quote per distinct underlying.
    und_px = _underlying_prices([r.get("symbol") for r in rows if r.get("asset_type") == "OPTION"])
    # Symbols with a working SELLTOCLOSE — being liquidated right now (e.g. an account reset
    # placed the closes, which fill at the next open). These must read as CLOSING, not as
    # orphaned UNMANAGED risk that nobody is acting on.
    closing = {str(c.get("symbol") or "").upper(): c for c in (view.get("pending_closes") or [])}
    # Broker-side protective STOPS (resting StopMarket, far below price) — NOT closes. Shown in the
    # Stop column so a held+protected position doesn't falsely read as "closing".
    stops = {str(s.get("symbol") or "").upper(): s.get("stop_price")
             for s in (view.get("pending_stops") or [])}
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        # Total initial cost in real dollars (option premium x100 x contracts) — computed for
        # EVERY row up front, before any status branch, so a closing/unmanaged row still shows
        # its cost. (A stray `continue` here once blanked the Cost column on closing rows.)
        mult = 100 if r.get("asset_type") == "OPTION" else 1
        qty_abs = abs(float(r.get("quantity") or 0))
        r["initial_cost"] = round(float(r.get("entry_price") or 0) * mult * qty_abs, 2)
        # Net cash paid at ENTRY, SIGNED — the true "what we paid": + = a DEBIT (you paid — a long, or a
        # bought wing), − = a CREDIT (you were paid — a short option leg). Unlike "Cost" (always the
        # positive notional), this shows the cash DIRECTION and sums across a condor to its net basis
        # (a net credit for short premium).
        r["net_paid"] = round(float(r.get("entry_price") or 0) * mult * float(r.get("quantity") or 0), 2)
        # Full-contract CURRENT value + the underlying spot, so the operator can check the math:
        # underlying price -> premium/sh -> x100xqty = total contract.
        if r.get("asset_type") == "OPTION":
            r["current_value"] = round(float(r.get("current_price") or 0) * mult * qty_abs, 2)
            u = sym.split()[0] if " " in sym else None
            if u:
                r["underlying"] = u
                if r.get("underlying_price") is None:
                    r["underlying_price"] = und_px.get(u)
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
            elif r.get("managed_by_greyline"):
                # a managed option with no per-leg ATR doctrine is a VRP condor leg — managed as a
                # UNIT by the variance-premium engine (defined-risk wings, 50% profit-take, gamma
                # defense, DTE), NOT by a per-leg stop. Surface the condor's UNIT stop/TP so the
                # Stop/Take-Profit columns show what actually protects it instead of a blank dash.
                r["status"] = "MANAGED"
                r["stage"] = "VRP condor leg · managed as a unit (defined-risk · 50% profit / gamma / DTE)"
                r["condor_levels"] = condor_levels.get(sym)
        else:
            # held equity — show the STRATEGY's real DYNAMIC exit (200-DMA break / backwardation),
            # NOT the 35% disaster backstop. The broker's 35% stop still rests as a crash backstop.
            dyn = _dynamic_exit(sym, r.get("current_price"))
            if dyn:
                r["stop_loss"] = dyn["stop_loss"]
                r["stage"] = dyn["stage"]
                r["tp_note"] = dyn["tp_note"]
                r["disaster_backstop"] = stops.get(sym)     # the 35% broker stop, kept as a footnote
            elif stops.get(sym) is not None:
                r["stop_loss"] = stops.get(sym)

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
            "net_paid": round(float(limit or 0) * mult * abs(float(pb.get("quantity") or 0)), 2),  # a buy = debit you'll pay
            "status": "PENDING", "stage": f"waiting · limit ${limit}" if limit else "waiting",
        })

    # CONDOR AS A UNIT: group VRP legs by their condor (underlying + expiry), attach the NET P&L, and
    # show the stop/TP ONCE — on the primary leg — instead of repeating the same condor-level number
    # on every leg (which read as "N separate positions all targeting $19").
    from collections import defaultdict
    condor_groups = defaultdict(list)
    for r in rows:
        if r.get("condor_levels"):
            parts = str(r.get("symbol") or "").split()
            key = (parts[0], parts[1][:6]) if len(parts) >= 2 else (str(r.get("symbol")),)
            condor_groups[key].append(r)
    for legs in condor_groups.values():
        net = round(sum(float(l.get("unrealized_pnl") or 0) for l in legs), 2)
        und = (legs[0].get("condor_levels") or {}).get("condor") or legs[0].get("underlying") or "condor"
        for i, l in enumerate(legs):
            l["condor_net_pnl"] = net
            l["condor_primary"] = (i == 0)
            l["condor_leg"] = f"{i + 1}/{len(legs)}"
            # EVERY leg keeps the condor's stop/TP — they are the CONDOR's ONE shared stop and ONE
            # take-profit (the whole unit exits together), shown on each row so no leg reads as
            # having no risk management. The stage names the condor + leg + the unit's net P/L.
            l["stage"] = f"{und} condor · leg {i + 1}/{len(legs)} · net P/L ${net}"

    # DEGRADED-READ GUARD (mirror account_summary): on a failed broker read, positions are UNKNOWN, not
    # zero. Emitting open_count=0 / total_unrealized_pnl=0.0 shipped a real-looking FLAT BOOK to any
    # consumer (pager, API client) — the same fantasy class the money tiles already guard against. Null the
    # counts/totals and flag degraded so no consumer can read the zeros as "we hold nothing".
    reads_ok = view.get("reads_ok")
    if not reads_ok:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account_mode": view.get("account_mode"),
            "account_label": view.get("account_label"),
            "reads_ok": False, "degraded": True,
            "open_positions": [],
            "open_count": None, "equity_count": None, "option_count": None,
            "total_unrealized_pnl": None, "total_notional": None,
            "status": "OPEN_POSITIONS_BROKER_READ_DEGRADED",
        }

    total_pnl = round(sum(r.get("unrealized_pnl") or 0 for r in rows), 2)
    total_notional = round(sum(abs((r.get("current_price") or 0) * (r.get("quantity") or 0)) for r in rows), 2)
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "account_mode": view.get("account_mode"),
        "account_label": view.get("account_label"),
        "reads_ok": reads_ok,
        "open_positions": rows,
        "open_count": len(rows),
        "equity_count": len([r for r in rows if r.get("asset_type") != "OPTION"]),
        "option_count": len([r for r in rows if r.get("asset_type") == "OPTION"]),
        "total_unrealized_pnl": total_pnl,
        "total_notional": total_notional,
        "status": "OPEN_POSITIONS_READY",
    }
