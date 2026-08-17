"""Rolling 2-day transaction ledger for the dashboard: yesterday's completed session + today's running
tally. It is a PURE FUNCTION of (current ET date, the sleeve ledgers' own timestamps) — so it "rolls"
automatically: at each open the new day's trades land under Today, what was Today becomes Yesterday (the
most recent prior session), and anything older than that drops off. No persistence, no nightly shift job.

Sources are GreyLine's OWN ledgers (what it actually booked): the momentum/equity ledger and the VRP +
earnings condor ledger. Each record yields up to two transaction EVENTS — an OPEN (at its open timestamp)
and, if CLOSED, a CLOSE (at closed_at, carrying realized P&L). Timestamps are stored naive-UTC; they are
converted to America/New_York so the day buckets match the trading session the operator sees.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


class TransactionLedgerEngine:

    MARKET_TZ = ZoneInfo("America/New_York")
    EQUITY_LEDGER = Path("app/data/paper_trading/paper_trade_ledger.jsonl")
    VRP_LEDGER = Path("app/data/options_paper_trading/vrp_short_premium_ledger.jsonl")
    OPT_LEDGER = Path("app/data/options_paper_trading/options_paper_trade_ledger.jsonl")
    # The direct-to-broker ETF sleeves (trend/carry/low-vol/managed-futures/T-bill) write to NONE of the
    # ledgers above — they book straight to the broker and log the order intent here. Without this the
    # table read "0 txn" on days those sleeves actively rebalanced. momentum + condors are EXCLUDED (they
    # already appear via the equity/VRP/OPT ledgers) so nothing is double-counted.
    EXEC_LEDGER = Path("app/data/execution/order_intent.jsonl")
    _ETF_SLEEVES = {"trend", "carry", "vol_carry", "low_vol", "managed_futures", "tbill", "xs_momentum"}
    # The order-intent log carries no per-order realized P&L, so an ETF SELL's P&L is reconstructed by
    # FIFO-matching it against that sleeve+symbol's own prior BUYs in this same log (see
    # _attach_etf_realized). Prices are the recorded LIMIT (intended fill) -> the result is an estimate.

    # Outcome-NEUTRAL exit labels. A close reason must never read like a result (e.g. the old
    # "EARNINGS_CRUSH_CAPTURED" wore a "captured" badge on a losing trade). The reason names the TRIGGER;
    # the realized P&L (shown right beside it) names the OUTCOME.
    _REASON_LABELS = {
        "EARNINGS_CRUSH_CAPTURED": "post-earnings exit",     # legacy rows keep the old value; humanize both
        "POST_EARNINGS_EXIT": "post-earnings exit",
        "MATURITY_LIQUIDATION": "expiry liquidation",
        "DTE_LIQUIDATION": "near-expiry exit",
        "ATR_STOP": "ATR stop",
    }

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _close_detail(self, reason, pnl):
        """Humanized, outcome-neutral exit trigger + the realized P&L outcome beside it."""
        r = str(reason or "closed")
        human = self._REASON_LABELS.get(r.upper(), r.replace("_", " ").lower())
        if pnl is None:
            return human
        tag = "gain" if pnl > 0 else ("loss" if pnl < 0 else "flat")
        return f"{human} · {'+' if pnl >= 0 else '-'}${abs(pnl):.0f} {tag}"

    @staticmethod
    def _read(path):
        try:
            return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def _events(self):
        """Flatten every ledger record into OPEN / CLOSE transaction events."""
        ev = []

        # VRP + earnings condors (opened_at / closed_at, defined-risk credit)
        for r in self._read(self.VRP_LEDGER):
            sleeve = "earnings" if str(r.get("strategy")) == "earnings_vol" else "vrp_condor"
            qty = r.get("quantity")
            if r.get("opened_at"):
                cr = self._f(r.get("credit_total"))
                ev.append({"ts": r["opened_at"], "sleeve": sleeve, "symbol": r.get("symbol"),
                           "action": "OPEN", "quantity": qty,
                           "detail": (f"condor · credit ${cr:+.0f}" if cr is not None else "condor"),
                           "pnl": None})
            if str(r.get("status")).upper() == "CLOSED" and r.get("closed_at"):
                _pnl = self._f(r.get("realized_pnl"))
                ev.append({"ts": r["closed_at"], "sleeve": sleeve, "symbol": r.get("symbol"),
                           "action": "CLOSE", "quantity": qty,
                           "detail": self._close_detail(r.get("close_reason"), _pnl), "pnl": _pnl})

        # equity (momentum) + any long-option contracts: open ts is `timestamp` (record creation), close is closed_at
        for r in (self._read(self.EQUITY_LEDGER) + self._read(self.OPT_LEDGER)):
            is_opt = " " in str(r.get("symbol") or "")
            sleeve = "options" if is_opt else "momentum"
            qty = r.get("quantity") if r.get("quantity") is not None else r.get("shares")
            open_ts = r.get("opened_at") or r.get("timestamp")
            if open_ts:
                px = self._f(r.get("entry_price"))
                bias = str(r.get("directional_bias") or "").upper()
                detail = " · ".join(x for x in [bias.title() if bias else "",
                                                (f"@ ${px:.2f}" if px is not None else "")] if x) or "opened"
                ev.append({"ts": open_ts, "sleeve": sleeve, "symbol": r.get("symbol"),
                           "action": "OPEN", "quantity": qty, "detail": detail, "pnl": None})
            if str(r.get("status")).upper() == "CLOSED" and r.get("closed_at"):
                _pnl = self._f(r.get("realized_pnl"))
                ev.append({"ts": r["closed_at"], "sleeve": sleeve, "symbol": r.get("symbol"),
                           "action": "CLOSE", "quantity": qty,
                           "detail": self._close_detail(r.get("close_reason"), _pnl), "pnl": _pnl})

        # direct-to-broker ETF sleeves — their trades are order INTENTS (BUY/SELL rebalances, not clean
        # opens/closes), logged with a decision-time timestamp (`ts`). The order-intent log carries no
        # per-trade realized P&L, so a BUY stays blank (a buy realizes nothing) and a SELL is enriched
        # afterwards from the sleeve trade ledger's `close` rows (_attach_etf_realized).
        etf = []
        for it in self._read(self.EXEC_LEDGER):
            sleeve = str(it.get("strategy") or "")
            if sleeve not in self._ETF_SLEEVES or it.get("direct"):   # skip momentum/condors + direct fills
                continue
            if not it.get("order_id"):                                # BLOCKED/rejected order (no broker id)
                continue                                              # never became a fill — drop it entirely
            ts = it.get("ts")
            action = str(it.get("action") or "").upper()
            if not ts or action not in ("BUY", "SELL"):
                continue
            lim = self._f(it.get("limit"))
            etf.append({"ts": ts, "sleeve": sleeve, "symbol": it.get("symbol"), "action": action,
                        "quantity": it.get("qty"), "_px": lim,
                        "detail": (f"@ ${lim:.2f}" if lim else "market") + (" · limit" if lim else ""),
                        "pnl": None})
        self._attach_etf_realized(etf)
        ev.extend(etf)
        return ev

    def _carried_basis(self):
        """FIFO the ARCHIVED order logs (preserved by every reset) to reconstruct the open BUY lots carried
        into the current log — the real cost basis of shares 'bought before this log began'. Returns
        {(sleeve, symbol): deque([[qty, price], ...])}. Read-only; archives never change. This is the 'seed
        cost basis' so a sell of carried-over shares matches a real (est) basis instead of reading n/a."""
        from collections import defaultdict, deque
        from pathlib import Path
        rows = []
        for a in sorted(Path("app/data/_archive").glob("reset-*/order_intent.jsonl")):
            for it in self._read(a):
                sleeve = str(it.get("strategy") or "")
                action = str(it.get("action") or "").upper()
                if sleeve in self._ETF_SLEEVES and not it.get("direct") and action in ("BUY", "SELL"):
                    rows.append((str(it.get("ts")), sleeve, str(it.get("symbol") or "").upper(),
                                 action, abs(self._f(it.get("qty")) or 0.0), self._f(it.get("limit"))))
        groups = defaultdict(list)
        for ts, sleeve, sym, action, qty, px in rows:
            groups[(sleeve, sym)].append((ts, action, qty, px))
        out = {}
        for key, evs in groups.items():
            evs.sort(key=lambda x: x[0])
            lots = deque()
            for ts, action, qty, px in evs:
                if action == "BUY":
                    if px and qty:
                        lots.append([qty, px])
                elif qty:                                   # SELL consumes carried lots FIFO
                    rem = qty
                    while rem > 0 and lots:
                        take = min(lots[0][0], rem)
                        lots[0][0] -= take
                        rem -= take
                        if lots[0][0] <= 0:
                            lots.popleft()
            if lots:
                out[key] = lots
        return out

    def _broker_entry_prices(self):
        """{SYMBOL: broker average cost} from the live positions — the final cost-basis fallback for shares
        a sleeve holds via cross-sleeve attribution and never bought in any log. Fail-safe -> {} on error."""
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            out = {}
            for p in (BrokerAccountViewEngine().snapshot().get("positions") or []):
                sym = str(p.get("symbol") or "").split()[0].upper()
                ep = self._f(p.get("entry_price"))
                if sym and ep > 0:
                    out[sym] = ep
            return out
        except Exception:
            return {}

    def _attach_etf_realized(self, etf_events):
        """Fill the P/L column on ETF SELL rows by FIFO-matching each sell against that sleeve+symbol's own
        prior BUYs — SEEDED with the carried-over lots reconstructed from the archived logs (_carried_basis),
        so a sell of shares bought before this log still matches a real (est) cost. realized = sum over
        matched lots of (sell_px - buy_px) * qty (recorded LIMIT prices -> estimate). A BUY realizes nothing;
        only a sell with no basis anywhere (current log OR archive) stays blank rather than inventing one."""
        from collections import defaultdict, deque
        carried = self._carried_basis()
        entry_by_sym = self._broker_entry_prices()          # FINAL fallback: the broker's own cost basis
        groups = defaultdict(list)
        for e in etf_events:
            groups[(e["sleeve"], str(e["symbol"] or "").upper())].append(e)
        for gkey, evs in groups.items():
            sym = gkey[1]
            evs.sort(key=lambda x: str(x["ts"]))
            lots = carried.get(gkey) or deque()             # SEED with carried-over basis, then live buys
            for e in evs:
                px = self._f(e.get("_px"))
                qty = abs(self._f(e.get("quantity")) or 0.0)
                if e["action"] == "BUY":
                    if px and qty:
                        lots.append([qty, px])
                    continue
                if e["action"] != "SELL" or not qty:
                    continue
                remaining, realized, matched = qty, 0.0, 0.0
                broker_basis = False
                while remaining > 0 and lots:
                    lot = lots[0]
                    take = min(lot[0], remaining)
                    if px and lot[1]:
                        realized += (px - lot[1]) * take
                        matched += take
                    lot[0] -= take
                    remaining -= take
                    if lot[0] <= 0:
                        lots.popleft()
                # ADOPTED shares (held via cross-sleeve attribution, never bought in any log): fall back to
                # the BROKER's own average cost for the symbol — the real basis of the shares, whoever booked
                # them. Only for the still-uncovered remainder, so a logged basis always wins.
                entry = entry_by_sym.get(sym)
                if remaining > 0 and px and entry:
                    realized += (px - entry) * remaining
                    matched += remaining
                    remaining = 0
                    broker_basis = True
                if matched > 0:                             # at least partly basised -> show it (est)
                    e["pnl"] = round(realized, 2)
                    if "est" not in e["detail"]:
                        e["detail"] = e["detail"] + (" · est P&L (broker cost)" if broker_basis else " · est P&L")
                else:                                        # NO basis anywhere -> honest 'n/a', never faked
                    e["detail"] = e["detail"] + " · P&L n/a (bought before this log began)"

    def _to_et(self, iso):
        """Naive-UTC ISO -> ET-aware datetime (raises on unparseable, caller filters)."""
        dt = datetime.fromisoformat(str(iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self.MARKET_TZ)

    @staticmethod
    def _by_position(evs):
        """Net every fill on a name into one row: {sleeve, symbol, bought, sold, fills, realized_pnl}.
        realized_pnl sums the P&L-bearing closes (None if the name had none). This is the P&L story —
        it turns 40 SVXY churn legs into a single 'carry SVXY: +$X net' line."""
        pos = {}
        for e in evs:
            k = (e.get("sleeve"), e.get("symbol"))
            a = pos.setdefault(k, {"sleeve": e.get("sleeve"), "symbol": e.get("symbol"),
                                   "bought": 0, "sold": 0, "fills": 0, "_pnl": 0.0, "_pnl_rows": 0})
            try:
                q = abs(int(e.get("quantity"))) if e.get("quantity") is not None else 0
            except (TypeError, ValueError):
                q = 0
            if e.get("action") in ("BUY", "OPEN"):
                a["bought"] += q
            elif e.get("action") in ("SELL", "CLOSE"):
                a["sold"] += q
            a["fills"] += 1
            if e.get("pnl") is not None:
                a["_pnl"] += e["pnl"]
                a["_pnl_rows"] += 1
        out = []
        for a in pos.values():
            a["realized_pnl"] = round(a.pop("_pnl"), 2) if a.pop("_pnl_rows") else None
            out.append(a)
        # losers first (most negative), names with a P&L before names without, then most fills
        out.sort(key=lambda r: (r["realized_pnl"] is None, r["realized_pnl"] if r["realized_pnl"] is not None else 0,
                                -r["fills"]))
        return out

    def _enrich_unrealized(self, by_position):
        """Enrich the BY-POSITION rows with UNREALIZED P&L AND drop phantom rows, using the live broker
        holdings as truth. Returns the cleaned list (fail-safe: on a broker-read error returns the input
        unchanged so realized P&L still renders).

        PHANTOM DROP: a row that is net-LONG (bought > sold) but the broker holds NONE of that symbol and it
        never realized anything is an order the deployment caps REJECTED — it never became a position, so it
        must not appear as one. Net-seller / realized rows are kept (real activity).

        UNREALIZED: the broker's total unrealized for a held symbol is split across that symbol's net-long
        rows by their displayed net (bought − sold), so every net-long sleeve shows its slice and the slices
        sum to the broker's real unrealized (aggregate-truthful, per-row complete)."""
        from collections import defaultdict
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            positions = BrokerAccountViewEngine().snapshot().get("positions", []) or []
        except Exception:
            return by_position
        held_upnl = defaultdict(float)
        for p in positions:
            sym = str(p.get("symbol") or "").split()[0].upper()      # OSI option symbols carry spaces
            if sym and abs(self._f(p.get("quantity")) or 0.0) > 0:
                held_upnl[sym] += self._f(p.get("unrealized_pnl")) or 0.0
        # EMPTY-READ GUARD: a broker read showing ZERO holdings while we have net-long rows is almost
        # certainly degraded (an all-positions-vanished event is implausible). Don't drop every row as a
        # phantom on a bad read — leave the rows untouched (same fail-closed pattern as the sleeve ledger).
        if not held_upnl and any((int(r.get("bought") or 0) - int(r.get("sold") or 0)) > 0 for r in by_position):
            return by_position
        cleaned, rows_by_sym = [], defaultdict(list)
        for row in by_position:
            sym = str(row.get("symbol") or "").upper()
            net = int(row.get("bought") or 0) - int(row.get("sold") or 0)
            if net > 0 and sym not in held_upnl and row.get("realized_pnl") is None:
                continue                                             # rejected-buy phantom — drop it
            cleaned.append(row)
            rows_by_sym[sym].append(row)
        for sym, rows in rows_by_sym.items():
            if sym not in held_upnl:
                continue
            upnl = round(held_upnl[sym], 2)
            longs = [(r, max(0, int(r.get("bought") or 0) - int(r.get("sold") or 0))) for r in rows]
            tot = sum(w for _, w in longs)
            net_rows = [(r, w) for r, w in longs if w > 0]
            if tot <= 0 or not net_rows:
                continue
            running = 0.0
            for i, (row, w) in enumerate(net_rows):
                share = round(upnl - running, 2) if i == len(net_rows) - 1 else round(upnl * w / tot, 2)
                running += share
                row["unrealized_pnl"] = share
        return cleaned

    def rolling(self):
        dated = []
        for e in self._events():
            try:
                dt = self._to_et(e["ts"])
                dated.append({**e, "_date": dt.date(), "et_time": dt.strftime("%H:%M"),
                              "_sort": dt.isoformat()})
            except Exception:
                continue

        today = datetime.now(self.MARKET_TZ).date()
        yday = today - timedelta(days=1)                               # the ACTUAL calendar day before today
        today_ev = [e for e in dated if e["_date"] == today]
        yday_ev = [e for e in dated if e["_date"] == yday]             # empty if yesterday had no trades (e.g. a weekend)

        def pack(evs, day, running):
            evs = sorted(evs, key=lambda x: x["_sort"])
            pnls = [e["pnl"] for e in evs if e.get("pnl") is not None]
            return {
                "date": day.isoformat() if day else None,
                "count": len(evs),
                # ETF-sleeve rebalances are BUY/SELL, not clean OPEN/CLOSE — count a BUY as an open-side
                # event and a SELL as a close-side event so the summary stays coherent across sleeve types.
                "opens": sum(1 for e in evs if e["action"] in ("OPEN", "BUY")),
                "closes": sum(1 for e in evs if e["action"] in ("CLOSE", "SELL")),
                "realized_pnl": round(sum(pnls), 2) if pnls else 0.0,
                "realized_label": "running" if running else "session",
                # BY POSITION: collapse the rebalance churn (dozens of BUY/SELL legs on one name) into ONE
                # line per (sleeve, symbol) with its NET realized P&L — the actual "what did each name do"
                # view. realized_pnl is None (not 0) when a name had no P&L-bearing close, so it reads "—"
                # instead of a fake $0. Losers first (most negative net P&L), then most-active names.
                "by_position": self._by_position(evs),
                "transactions": [{k: e.get(k) for k in
                                  ("et_time", "sleeve", "symbol", "action", "quantity", "detail", "pnl")}
                                 for e in evs],
            }

        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "today": pack(today_ev, today, running=True),
            "yesterday": pack(yday_ev, yday, running=False),
            "note": ("Rolling 2 calendar days: today's running tally + the actual day before today (yesterday). "
                     "Pure function of the ET date + ledger timestamps — if yesterday was a weekend/holiday with "
                     "no trades it simply shows 0. Source: GreyLine's own sleeve ledgers."),
            "status": "TRANSACTIONS_ROLLING_READY",
        }
        # unrealized + phantom-drop are a CURRENT-BOOK reconciliation — they apply to every net-long row in
        # the 2-day window, NOT just today's. On a weekend / pre-open the held positions were all opened in
        # the PRIOR session, so enriching only "today" left them ALL showing "—" (and left flattened/rejected
        # names lingering as phantom rows). Enrich BOTH days as ONE set: each held name shows its unrealized
        # exactly once (the broker's unrealized split across its net-long sleeve rows, no double-count) and a
        # non-held phantom drops from whichever day it's in. Same dict objects -> identity filter keeps order.
        try:
            combined = out["today"]["by_position"] + out["yesterday"]["by_position"]
            kept = {id(r) for r in self._enrich_unrealized(combined)}
            out["today"]["by_position"] = [r for r in out["today"]["by_position"] if id(r) in kept]
            out["yesterday"]["by_position"] = [r for r in out["yesterday"]["by_position"] if id(r) in kept]
        except Exception:
            pass
        return out
