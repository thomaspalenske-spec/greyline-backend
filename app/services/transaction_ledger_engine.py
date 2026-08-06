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
from datetime import datetime, timezone
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

    def _attach_etf_realized(self, etf_events):
        """Fill the P/L column on ETF SELL rows by FIFO-matching each sell against that sleeve+symbol's own
        prior BUYs in the order log. realized = sum over matched lots of (sell_px - buy_px) * qty, using the
        recorded LIMIT prices (intended fill) — an ESTIMATE, labeled as such. Covers EVERY sell (all days),
        self-consistent, and independent of any downstream reconciler. A BUY realizes nothing (stays blank);
        a sell qty with no prior buy in the log (position predates logging) leaves that portion unbasised —
        if NONE of it can be matched the row stays blank rather than inventing a number."""
        from collections import defaultdict, deque
        groups = defaultdict(list)
        for e in etf_events:
            groups[(e["sleeve"], str(e["symbol"] or "").upper())].append(e)
        for evs in groups.values():
            evs.sort(key=lambda x: str(x["ts"]))
            lots = deque()                                  # FIFO open BUY lots: [qty, price]
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
                if matched > 0:                             # at least partly basised -> show it (est)
                    e["pnl"] = round(realized, 2)
                    if "est" not in e["detail"]:
                        e["detail"] = e["detail"] + " · est P&L"
                    if matched < qty:                       # part of the sell had no logged buy to match
                        e["detail"] = e["detail"] + f" (basis for {int(qty - matched)} pre-log)"
                else:                                        # NO logged buy -> honest 'no basis', never faked
                    e["detail"] = e["detail"] + " · P&L n/a (bought before this log began)"

    def _to_et(self, iso):
        """Naive-UTC ISO -> ET-aware datetime (raises on unparseable, caller filters)."""
        dt = datetime.fromisoformat(str(iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self.MARKET_TZ)

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
        today_ev = [e for e in dated if e["_date"] == today]
        prior_dates = sorted({e["_date"] for e in dated if e["_date"] < today}, reverse=True)
        yday = prior_dates[0] if prior_dates else None                 # most recent PRIOR session (skips weekends)
        yday_ev = [e for e in dated if yday and e["_date"] == yday]

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
                "transactions": [{k: e.get(k) for k in
                                  ("et_time", "sleeve", "symbol", "action", "quantity", "detail", "pnl")}
                                 for e in evs],
            }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "today": pack(today_ev, today, running=True),
            "yesterday": pack(yday_ev, yday, running=False),
            "note": ("Rolling 2-day window: today's running tally + the prior completed session. It rolls at "
                     "the open automatically (pure function of the ET date + ledger timestamps) — older than "
                     "the prior session drops off. Source: GreyLine's own sleeve ledgers."),
            "status": "TRANSACTIONS_ROLLING_READY",
        }
