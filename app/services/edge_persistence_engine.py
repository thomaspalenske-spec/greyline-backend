"""Live per-sleeve edge scorecard — the discipline GreyLine lacked: measure whether each strategy is
ACTUALLY earning, so decayed ones can be retired on evidence instead of narrative.

Medallion's core discipline isn't a magic signal — it's relentlessly retiring signals as they decay.
That requires knowing, per strategy, whether it's still working. GreyLine measured its edges ONCE
(backtest / forward panel) and then flew blind on the live book. This records a daily per-sleeve mark
so, over time, each sleeve gets an honest live track record — the foundation for evidence-based
capital (retire the dead, keep the living) and the thing that would have cut momentum long before -41%.

Attribution is by instrument, which is clean because the sleeves trade distinct things:
  carry -> SVXY | trend -> the ETF basket | tbill -> SGOV | premium (VRP+earnings) -> options |
  momentum -> any other equity.

v1 tracks OPEN-POSITION P&L per sleeve (directly attributable). Full realized attribution across
closed trades is the documented v2 — noted, not faked. Read-only; it never trades.
"""

import json
from datetime import datetime
from pathlib import Path


class EdgePersistenceEngine:

    DIR = Path("app/data/edge_persistence")
    LEDGER = DIR / "daily_marks.jsonl"

    CARRY = {"SVXY"}
    TREND = {"QQQM", "IWM", "TLT", "GLDM", "EFA", "DBC"}
    TBILL = {"SGOV"}
    MIN_DAYS = 10           # below this, a sleeve has too little history to judge

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _sleeve_of(cls, symbol, asset_type):
        sym = str(symbol or "").upper()
        if str(asset_type or "").upper() in ("STOCKOPTION", "OPTION"):
            return "premium"                      # VRP + earnings condors
        base = sym.split()[0] if sym else sym
        if base in cls.CARRY:
            return "carry"
        if base in cls.TREND:
            return "trend"
        if base in cls.TBILL:
            return "tbill"
        return "momentum"                         # any other equity

    def _rows(self):
        try:
            return [json.loads(l) for l in self.LEDGER.read_text().splitlines() if l.strip()]
        except Exception:
            return []

    def snapshot(self):
        """Record today's per-sleeve open-position marks (one set of rows per UTC day; last wins)."""
        try:
            from app.services.broker_account_view_engine import BrokerAccountViewEngine
            positions = BrokerAccountViewEngine().snapshot().get("positions", []) or []
        except Exception as e:
            return {"status": "EDGE_PERSISTENCE_DEGRADED", "error": repr(e)[:100]}

        today = datetime.utcnow().date().isoformat()
        agg = {}
        for p in positions:
            s = self._sleeve_of(p.get("symbol"), p.get("asset_type") or p.get("AssetType"))
            a = agg.setdefault(s, {"deployed": 0.0, "unrealized": 0.0, "market_value": 0.0, "positions": 0})
            a["deployed"] += self._f(p.get("entry_price")) * self._f(p.get("quantity"))
            a["unrealized"] += self._f(p.get("unrealized_pnl"))
            a["market_value"] += self._f(p.get("current_price")) * self._f(p.get("quantity"))
            a["positions"] += 1

        # keep only the LATEST snapshot per (date, sleeve): drop today's prior rows, then append fresh
        rows = [r for r in self._rows() if r.get("date") != today]
        for sleeve, a in agg.items():
            rows.append({"date": today, "sleeve": sleeve,
                         "deployed": round(a["deployed"], 2), "unrealized": round(a["unrealized"], 2),
                         "market_value": round(a["market_value"], 2), "positions": a["positions"],
                         "ts": datetime.utcnow().isoformat()})
        try:
            self.DIR.mkdir(parents=True, exist_ok=True)
            with open(self.LEDGER, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        except Exception as e:
            return {"status": "EDGE_PERSISTENCE_WRITE_FAILED", "error": repr(e)[:100]}
        return {"status": "EDGE_PERSISTENCE_RECORDED", "date": today,
                "sleeves": {s: round(a["unrealized"], 2) for s, a in agg.items()}}

    def report(self):
        rows = self._rows()
        by = {}
        for r in rows:
            by.setdefault(r.get("sleeve"), []).append(r)
        out = {}
        for sleeve, recs in by.items():
            recs.sort(key=lambda x: x.get("date", ""))
            days = len(recs)
            latest = recs[-1]
            neg_days = sum(1 for r in recs if self._f(r.get("unrealized")) < 0)
            # verdict: honest about insufficient history; else flag persistent bleeders
            if days < self.MIN_DAYS:
                verdict = f"ACCUMULATING ({days}/{self.MIN_DAYS}d — too little to judge)"
            elif neg_days >= 0.7 * days:
                verdict = "DECAYED? — open P&L negative most days; candidate to retire"
            elif neg_days <= 0.3 * days:
                verdict = "WORKING — open P&L positive most days"
            else:
                verdict = "MIXED — watch"
            out[sleeve] = {"days_tracked": days, "current_unrealized": self._f(latest.get("unrealized")),
                           "current_deployed": self._f(latest.get("deployed")),
                           "negative_day_fraction": round(neg_days / max(1, days), 2), "verdict": verdict}
        return {"timestamp": datetime.utcnow().isoformat(), "sleeves": out,
                "note": ("v1 tracks OPEN-position P&L per sleeve; realized attribution across closed "
                         "trades is the v2 needed for a full decay verdict."),
                "status": "EDGE_PERSISTENCE_REPORT"}
