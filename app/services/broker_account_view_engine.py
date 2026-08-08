"""The dashboard's ONLY window into account holdings — read straight from TradeStation.

Reads balances / positions / orders from whichever account the one selector
(`TradeStationAccountSourceEngine`) points at — the SIM paper account today, the real-money
account the moment the operator flips `GREYLINE_DASHBOARD_ACCOUNT_MODE=live`. Nothing here
touches the local paper ledger; if a position isn't booked at TradeStation, it does not
appear. That is the whole point: the dashboard can only ever show broker truth.

Read-only. Selecting the live account here shows real holdings; it cannot place an order.
"""

from datetime import datetime

from app.services.tradestation_account_source_engine import TradeStationAccountSourceEngine
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine
from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class BrokerAccountViewEngine:

    WORKING = ("received", "open", "queued", "sent", "partiallyfilled")

    def snapshot(self):
        src = TradeStationAccountSourceEngine().resolve()
        if not src.get("ok"):
            return {"timestamp": datetime.utcnow().isoformat(), "reads_ok": False,
                    "account_mode": src.get("mode"), "account_label": src.get("label"),
                    "error": src.get("error"), "positions": [], "orders_working": 0,
                    "equity": 0.0, "cash_balance": 0.0, "buying_power": 0.0,
                    "status": "BROKER_ACCOUNT_SOURCE_UNRESOLVED"}

        # BOUNDED RETRY: the account read intermittently gets STARVED (non-200 timeout) when the scheduler
        # cycle is saturating TradeStation — but it genuinely succeeds within a window. Without a retry a
        # single starved read fails-closed the whole view, which blocks trading (the exposure breaker) at
        # the open. This does NOT weaken safety: it still requires a REAL, fully-parsed 200 read (no stale
        # data, no fabrication) — it just tries a few times to catch a success instead of giving up on one.
        import time as _t
        bal = pos = ords = None
        for _attempt in range(4):
            bal = TradeStationBalanceLiveEngine().get_balance()
            pos = TradeStationPositionsLiveEngine().get_positions()
            ords = TradeStationOrdersLiveEngine().get_orders()
            _b = ((bal.get("response_json") or {}).get("Balances") or [])
            if (bal.get("http_status") == 200 and pos.get("http_status") == 200
                    and ords.get("http_status") == 200 and bal.get("response_json") and _b):
                break                                     # got a real read — stop retrying
            if _attempt < 3:
                _t.sleep(1.5)                             # brief backoff, then try to catch a clear window

        balances = ((bal.get("response_json") or {}).get("Balances") or [])
        b = balances[0] if balances else {}
        raw_positions = (pos.get("response_json") or {}).get("Positions") or []
        raw_orders = (ords.get("response_json") or {}).get("Orders") or []
        working = [o for o in raw_orders
                   if str(o.get("StatusDescription", "")).lower() in self.WORKING]

        # Pending limit BUY-to-open orders — what we've placed and are WAITING to fill at a
        # target price. Empty while entries are market orders; populates once entries are
        # limit orders. These are not positions yet, so the dashboard shows them as pending.
        pending_buys, pending_closes, pending_stops = [], [], []
        for o in working:
            leg = (o.get("Legs") or [{}])[0]
            buy_or_sell = str(leg.get("BuyOrSell") or "").lower()
            open_or_close = str(leg.get("OpenOrClose") or "").lower()
            sym = leg.get("Symbol")
            limit = _f(o.get("LimitPrice"))
            row = {
                "symbol": sym,
                "asset_type": "OPTION" if " " in str(sym or "") else "EQUITY",
                "quantity": _f(leg.get("Quantity")),
                "limit_price": round(limit, 2) if limit else None,
                "order_type": o.get("OrderType"),
                "status_desc": o.get("StatusDescription"),
                "order_id": o.get("OrderID"),
            }
            if buy_or_sell.startswith("buy") and open_or_close == "open":
                pending_buys.append(row)
            elif buy_or_sell.startswith("sell") and open_or_close == "close":
                if str(o.get("OrderType") or "") in ("StopMarket", "StopLimit"):
                    # A resting protective STOP (disaster stop, far below price) — NOT an active
                    # liquidation. It fires only if the position crashes. Surface it as the
                    # position's stop, NOT as "closing" (which falsely reads like the book is being
                    # dumped when it is actually held and protected).
                    row["stop_price"] = _f(o.get("StopPrice"))
                    pending_stops.append(row)
                else:
                    # A working Limit/Market SELLTOCLOSE = this position is being LIQUIDATED now.
                    pending_closes.append(row)

        # reads_ok requires the balance body to actually PARSE and carry a Balances record — not just
        # an HTTP 200. A gateway/auth interstitial can return 200 with a non-JSON body, leaving
        # response_json None → Balances=[] → equity 0 → a $10k / 0-position all-cash FANTASY that still
        # read as healthy. A real account read always returns >=1 Balance, so gating on it fails closed
        # on an empty/unparseable body. (Positions/Orders may legitimately be empty, so they aren't gated.)
        balances_ok = bool(bal.get("response_json")) and bool(balances)
        reads_ok = (bal.get("http_status") == 200 and pos.get("http_status") == 200
                    and ords.get("http_status") == 200 and balances_ok)

        positions = []
        for p in raw_positions:
            symbol = p.get("Symbol")
            # A TradeStation option symbol carries a space + expiry/strike ("ALAB 260828C315");
            # a bare ticker is equity.
            is_option = " " in str(symbol or "")
            mult = 100 if is_option else 1
            entry = _f(p.get("AveragePrice"))
            qty = _f(p.get("Quantity"))
            is_short = str(p.get("LongShort") or "").lower() == "short"
            direction = -1 if is_short else 1
            # Current price = the broker's MARK (MarketValue / qty / multiplier), NOT the
            # last-trade print. For illiquid options "Last" can be hours stale while the mark
            # tracks live; using Last made Current and P&L% disagree with the broker's own P&L
            # dollars. Fall back to Last only if MarketValue is missing.
            mv = _f(p.get("MarketValue"))
            last_trade = _f(p.get("Last"))
            mark = (abs(mv) / (abs(qty) * mult)) if (qty and mv) else 0.0
            last = mark if mark > 0 else last_trade
            pnl = _f(p.get("UnrealizedProfitLoss")) or (last - entry) * qty * direction * mult
            pnl_pct = ((last / entry - 1) * 100 * direction) if entry else 0.0
            # No stop/TP here. The real exits run on the UNDERLYING's move (the validated
            # ATR doctrine), and the open-positions route fills those in from the ledger for
            # GreyLine-managed positions. The old premium %-rule (-35%/+50% of entry) shown
            # here was stale — it contradicted the live doctrine AND leaked onto UNMANAGED
            # positions the route doesn't touch, so it's gone.
            stop_loss, targets = None, []
            positions.append({
                "symbol": symbol, "asset_type": "OPTION" if is_option else "EQUITY",
                "side": "SHORT" if is_short else "LONG",
                "quantity": qty, "shares": qty,
                "entry_price": round(entry, 2), "current_price": round(last, 2),
                "unrealized_pnl": round(pnl, 2), "unrealized_pnl_pct": round(pnl_pct, 2),
                "stop_loss": stop_loss, "targets": targets,
                "tps_filled": 0 if targets else None,
                "status": "OPEN", "stage": src.get("label"),
                "marked": "BROKER_LIVE",
            })

        # When degraded, capture WHY (the actual HTTP statuses) so the guard/banner can name the real cause
        # — "TradeStation HTTP 500 (broker-side outage)" vs a local transient — instead of always guessing
        # "busy scheduler cycle". broker_side is True on any 5xx (their server), else it's likely transient.
        read_detail, broker_side = None, False
        if not reads_ok:
            parts = []
            for name, resp in (("balances", bal), ("positions", pos), ("orders", ords)):
                hs = (resp or {}).get("http_status")
                if hs != 200:
                    parts.append(f"{name} HTTP {hs if hs is not None else 'no-response'}")
                    if isinstance(hs, int) and 500 <= hs <= 599:
                        broker_side = True
            if not parts and not balances_ok:
                parts.append("balances body empty/unparseable")
            read_detail = ", ".join(parts) or "unknown"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "reads_ok": reads_ok,
            "read_detail": read_detail,          # e.g. "positions HTTP 500, balances HTTP 500" when degraded
            "read_broker_side": broker_side,     # True -> TradeStation server error (5xx), not a local blip
            "account_mode": src.get("mode"),
            "account_id": src.get("account_id"),
            "account_label": src.get("label"),
            "host_kind": src.get("host_kind"),
            "equity": _f(b.get("Equity")),
            "cash_balance": _f(b.get("CashBalance")),
            "buying_power": _f(b.get("BuyingPower")),
            "positions": positions,
            "position_count": len(positions),
            "orders_working": len(working),
            "pending_buys": pending_buys,
            "pending_closes": pending_closes,
            "pending_stops": pending_stops,
            "status": "BROKER_ACCOUNT_VIEW_READY" if reads_ok else "BROKER_ACCOUNT_READ_DEGRADED",
        }
