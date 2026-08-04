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

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

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
                ev.append({"ts": r["closed_at"], "sleeve": sleeve, "symbol": r.get("symbol"),
                           "action": "CLOSE", "quantity": qty,
                           "detail": str(r.get("close_reason") or "closed"),
                           "pnl": self._f(r.get("realized_pnl"))})

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
                ev.append({"ts": r["closed_at"], "sleeve": sleeve, "symbol": r.get("symbol"),
                           "action": "CLOSE", "quantity": qty,
                           "detail": str(r.get("close_reason") or "closed"),
                           "pnl": self._f(r.get("realized_pnl"))})
        return ev

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
                "opens": sum(1 for e in evs if e["action"] == "OPEN"),
                "closes": sum(1 for e in evs if e["action"] == "CLOSE"),
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
