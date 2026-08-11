"""The dashboard's ONLY window into account holdings — read straight from TradeStation.

Reads balances / positions / orders from whichever account the one selector
(`TradeStationAccountSourceEngine`) points at — the SIM paper account today, the real-money
account the moment the operator flips `GREYLINE_DASHBOARD_ACCOUNT_MODE=live`. Nothing here
touches the local paper ledger; if a position isn't booked at TradeStation, it does not
appear. That is the whole point: the dashboard can only ever show broker truth.

Read-only. Selecting the live account here shows real holdings; it cannot place an order.
"""

import time as _clock
from datetime import datetime
from os import getenv

from app.services.tradestation_account_source_engine import TradeStationAccountSourceEngine
from app.services.tradestation_positions_live_engine import TradeStationPositionsLiveEngine
from app.services.tradestation_balance_live_engine import TradeStationBalanceLiveEngine
from app.services.tradestation_orders_live_engine import TradeStationOrdersLiveEngine


# SHARED READ-THROUGH CACHE (only-200-cached). Every snapshot() is 3 TradeStation HTTP calls
# (balance/positions/orders), and MANY consumers call snapshot() within the same scheduler cycle
# (exposure gate, reality guard, account-summary, dashboard tiles, sleeve sizing). Un-cached, those
# overlapping reads stack TS calls until the 3rd (orders) trips a 429 rate-limit — the observed flap.
# A short cache collapses the burst into ONE real read per window, which is what actually stops the 429
# (a retry can't: 429 means "call less"). It NEVER caches a degraded/fabricated read — only a fully-good
# reads_ok=True snapshot — so a cache hit is always real broker data, just up to TTL seconds old (age is
# labelled). TTL is short by default so a just-filled position surfaces fast at the open; the hard
# BookDeploymentCap remains the real over-deployment backstop regardless.
_SNAPSHOT_CACHE = {}          # account_id -> (monotonic_at, snapshot_dict)


def _cache_ttl():
    try:
        return float(getenv("GREYLINE_POSITIONS_CACHE_TTL_S", "10") or 10)
    except (TypeError, ValueError):
        return 10.0


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class BrokerAccountViewEngine:

    WORKING = ("received", "open", "queued", "sent", "partiallyfilled")

    def snapshot(self, allow_cache=True):
        src = TradeStationAccountSourceEngine().resolve()
        if not src.get("ok"):
            return {"timestamp": datetime.utcnow().isoformat(), "reads_ok": False,
                    "account_mode": src.get("mode"), "account_label": src.get("label"),
                    "error": src.get("error"), "positions": [], "orders_working": 0,
                    "equity": 0.0, "cash_balance": 0.0, "buying_power": 0.0,
                    "status": "BROKER_ACCOUNT_SOURCE_UNRESOLVED"}

        # READ-THROUGH CACHE: serve a very-recent, fully-good read instead of firing 3 more TS calls.
        # Only a reads_ok=True snapshot is ever cached, so a hit is always REAL broker data (age labelled).
        # allow_cache=False forces a fresh read for any caller that must not tolerate even TTL-seconds of lag.
        _acct = src.get("account_id")
        _ttl = _cache_ttl()
        if allow_cache and _ttl > 0 and _acct in _SNAPSHOT_CACHE:
            _at, _cached = _SNAPSHOT_CACHE[_acct]
            _age = _clock.monotonic() - _at
            if _age < _ttl and _cached.get("reads_ok"):
                out = dict(_cached)
                out["served_from_cache"] = True
                out["cache_age_seconds"] = round(_age, 1)
                return out

        # BOUNDED RETRY: the account read intermittently gets STARVED (non-200 timeout) when the scheduler
        # cycle is saturating TradeStation — but it genuinely succeeds within a window. Without a retry a
        # single starved read fails-closed the whole view, which blocks trading (the exposure breaker) at
        # the open. This does NOT weaken safety: it still requires a REAL, fully-parsed 200 read (no stale
        # data, no fabrication) — it just tries a few times to catch a success instead of giving up on one.
        import time as _t
        # Only-refetch-the-FAILED-sub-read retry. The three reads (balance/positions/orders) are independent;
        # under load one intermittently STARVES (transient non-200 timeout, NOT a 429 — verified 2026-08-11).
        # Re-fetching all three every attempt (a) triples the load and (b) needs all three to land clean in
        # the SAME attempt, which a flapping read rarely does. Instead, keep each sub-read once it returns a
        # good 200 and retry ONLY the one still failing — fewer calls, and the combined read converges. Still
        # requires a REAL fully-parsed 200 (no stale data, no fabrication); still respects 429 (never retry
        # into the throttle). Attempts/backoff tunable.
        def _bal_good(r):
            return bool(r) and r.get("http_status") == 200 and bool(r.get("response_json")) \
                and bool((r.get("response_json") or {}).get("Balances"))
        def _ok(r):
            return bool(r) and r.get("http_status") == 200
        try:
            _attempts = max(1, int(getenv("GREYLINE_BROKER_READ_ATTEMPTS", "6")))
        except (TypeError, ValueError):
            _attempts = 6
        bal = pos = ords = None
        for _attempt in range(_attempts):
            if not _bal_good(bal):
                bal = TradeStationBalanceLiveEngine().get_balance()
            if not _ok(pos):
                pos = TradeStationPositionsLiveEngine().get_positions()
            if not _ok(ords):
                ords = TradeStationOrdersLiveEngine().get_orders()
            if _bal_good(bal) and _ok(pos) and _ok(ords):
                break                                     # got a real read on every leg — stop retrying
            # 429 = "you are calling too often"; RETRYING AMPLIFIES it. Respect it: stop, fail-closed this
            # cycle (honest, not fabricated), let the window reset. Only the STILL-failing legs can 429.
            if any((r or {}).get("http_status") == 429 for r in (bal, pos, ords)):
                break
            if _attempt < _attempts - 1:
                _t.sleep(1.0 + 0.5 * _attempt)            # growing backoff — span a longer starvation pulse

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
        read_detail, broker_side, rate_limited = None, False, False
        if not reads_ok:
            parts = []
            for name, resp in (("balances", bal), ("positions", pos), ("orders", ords)):
                hs = (resp or {}).get("http_status")
                if hs != 200:
                    parts.append(f"{name} HTTP {hs if hs is not None else 'no-response'}")
                    if isinstance(hs, int) and 500 <= hs <= 599:
                        broker_side = True
                    if hs == 429:
                        rate_limited = True           # throttled — self-clears; we back off, don't retry
            if not parts and not balances_ok:
                parts.append("balances body empty/unparseable")
            read_detail = (", ".join(parts) or "unknown") + (" (rate-limited — backing off)" if rate_limited else "")

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "reads_ok": reads_ok,
            "read_detail": read_detail,          # e.g. "positions HTTP 500, balances HTTP 500" when degraded
            "read_broker_side": broker_side,     # True -> TradeStation server error (5xx), not a local blip
            "read_rate_limited": rate_limited,   # True -> HTTP 429 throttle; we back off (never retry into it)
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
        # cache only a fully-good read — a degraded/fabricated view must never be served from cache
        if allow_cache and reads_ok and _ttl > 0:
            _SNAPSHOT_CACHE[_acct] = (_clock.monotonic(), result)
        return result
