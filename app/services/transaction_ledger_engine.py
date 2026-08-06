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
    # The ETF sleeves' realized P&L lives HERE (the order-intent log carries none): the broker-delta
    # reconciler writes a `close` row with realized_pnl when a sleeve's position shrinks. We look these up
    # to fill the P/L column on ETF SELL rows. The order-intent `strategy` and the ledger `sleeve` use
    # different names for the same sleeve (carry<->vol_carry), so normalize before matching.
    SLEEVE_LEDGER = Path("app/data/paper_trading/sleeve_trade_ledger.jsonl")
    _SLEEVE_ALIAS = {"carry": "vol_carry", "vol_carry": "vol_carry", "trend": "trend",
                     "low_vol": "low_vol", "managed_futures": "managed_futures", "tbill": "tbill",
                     "xs_momentum": "xs_momentum"}

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
                        "quantity": it.get("qty"),
                        "detail": (f"@ ${lim:.2f}" if lim else "market") + (" · limit" if lim else ""),
                        "pnl": None})
        self._attach_etf_realized(etf)
        ev.extend(etf)
        return ev

    def _attach_etf_realized(self, etf_events):
        """Fill the P/L column on ETF SELL rows from the sleeve trade ledger's `close` rows (which DO
        carry realized_pnl, on a quote_estimate basis). Matched by (normalized sleeve, symbol, ET date);
        when a key has several sells the realized total is split across them by quantity so the DAY total
        is exact. A BUY realizes nothing and stays blank; a sell with no matching close (e.g. T-bill SGOV,
        which the reconciler doesn't track) also stays blank."""
        from collections import defaultdict
        closes = {}                                        # (sleeve_norm, symbol, et_date) -> total realized
        for r in self._read(self.SLEEVE_LEDGER):
            if str(r.get("kind")) != "close":
                continue
            pnl = self._f(r.get("realized_pnl"))
            if pnl is None:
                continue
            try:
                d = self._to_et(r.get("closed_at")).date()
            except Exception:
                continue
            sl = self._SLEEVE_ALIAS.get(str(r.get("sleeve")), str(r.get("sleeve")))
            closes[(sl, str(r.get("symbol") or "").upper(), d)] = \
                closes.get((sl, str(r.get("symbol") or "").upper(), d), 0.0) + pnl
        if not closes:
            return
        sells = defaultdict(list)
        for e in etf_events:
            if e["action"] != "SELL":
                continue
            try:
                d = self._to_et(e["ts"]).date()
            except Exception:
                continue
            sl = self._SLEEVE_ALIAS.get(e["sleeve"], e["sleeve"])
            sells[(sl, str(e["symbol"] or "").upper(), d)].append(e)
        for key, group in sells.items():
            total = closes.get(key)
            if total is None:
                continue
            qtys = [abs(self._f(e.get("quantity")) or 0.0) for e in group]
            tq = sum(qtys) or float(len(group))
            running = 0.0
            for i, e in enumerate(group):
                share = round(total - running, 2) if i == len(group) - 1 else round(total * (qtys[i] / tq), 2)
                running += share
                e["pnl"] = share
                if "est" not in e["detail"]:
                    e["detail"] = e["detail"] + " · est P&L"

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
