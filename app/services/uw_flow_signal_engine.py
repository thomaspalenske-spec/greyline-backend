import json
from pathlib import Path


class UWFlowSignalEngine:
    """
    Distil an Unusual Whales snapshot into a compact directional flow reading.

    The snapshots are real institutional options flow (~5 MB each, ~16 GB and growing)
    but unusable in that form. This extracts the one thing most likely to carry
    directional edge — aggressive (ask-side) premium — into a small per-symbol series
    that can actually be graded against forward returns:

      directional_flow = (call_ask_premium - put_ask_premium) / (both)   in [-1, +1]
        + = smart money aggressively BUYING CALLS (bullish)
        - = aggressively BUYING PUTS (bearish)

    Ask-side specifically = trades that lifted the offer, i.e. someone paying up to get
    in — the classic "conviction" flow, as opposed to passive bid-side fills.

    This does NOT touch the live decision. It is measurement infrastructure: the flow
    edge (alone, and as a gate on the price signal) has to be proven forward before it
    earns a place in the signal — the data is only days deep today.
    """

    OUT_DIR = Path("app/data/uw_flow")

    @staticmethod
    def _signals(snapshot):
        return ((snapshot.get("providers") or {}).get("UNUSUAL_WHALES") or {}).get("signals") or {}

    @staticmethod
    def _rows(value):
        if isinstance(value, dict):
            return value.get("data") or []
        return value or []

    def _flow_rows(self, snapshot):
        return self._rows(self._signals(snapshot).get("flow_per_strike_intraday"))

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _latest_date_rows(self, rows):
        """Keep only rows on the most recent date — daily signals repeat across intraday snaps."""
        dated = [r for r in rows if r.get("date")]
        if not dated:
            return rows
        latest = max(r["date"] for r in dated)
        return [r for r in dated if r["date"] == latest]

    def _skew(self, sig):
        """Options risk-reversal (25-delta call IV minus put IV). + = calls bid up = bullish."""
        rows = self._latest_date_rows(self._rows(sig.get("historical_risk_reversal_skew")))
        vals = [self._f(r.get("risk_reversal")) for r in rows]
        return round(sum(vals) / len(vals), 5) if vals else 0.0

    def _dealer_greeks(self, sig):
        """Net dealer gamma (GEX) and net delta across strikes — dealer positioning."""
        rows = self._latest_date_rows(self._rows(sig.get("greek_exposure_by_strike")))
        gex = sum(self._f(r.get("call_gex")) + self._f(r.get("put_gex")) for r in rows)
        delta = sum(self._f(r.get("call_delta")) + self._f(r.get("put_delta")) for r in rows)
        return round(gex, 2), round(delta, 2)

    def extract(self, snapshot):
        """One snapshot dict -> a compact flow record, or None if no usable flow."""
        symbol = snapshot.get("symbol") or snapshot.get("ticker")
        ts = snapshot.get("timestamp")
        rows = self._flow_rows(snapshot)
        if not symbol or not ts or not rows:
            return None

        def _s(rows_, key):
            tot = 0.0
            for r in rows_:
                try:
                    tot += float(r.get(key) or 0)
                except (TypeError, ValueError):
                    pass
            return tot

        call_ask = _s(rows, "call_premium_ask_side")
        put_ask = _s(rows, "put_premium_ask_side")
        net_premium = _s(rows, "net_premium")
        denom = call_ask + put_ask
        if denom <= 0:
            return None

        # Additional, DISTINCT institutional-positioning signals from the same snapshot —
        # graded in parallel by UWFlowGradingEngine so the data (not intuition) decides
        # which predict. These measure different things than aggressive premium flow:
        #   skew         : the shape of the vol surface (call vs put demand / hedging)
        #   dealer_gex   : dealer gamma positioning (pinning vs amplifying regime)
        #   dealer_delta : net directional dealer exposure
        sig = self._signals(snapshot)
        gex, dealer_delta = self._dealer_greeks(sig)

        return {
            "ts": ts,
            "symbol": str(symbol).upper(),
            "call_ask_premium": round(call_ask, 2),
            "put_ask_premium": round(put_ask, 2),
            "net_premium": round(net_premium, 2),
            "directional_flow": round((call_ask - put_ask) / denom, 4),
            "flow_bias": "BULLISH" if call_ask > put_ask else "BEARISH",
            "strikes": len(rows),
            "skew": self._skew(sig),
            "dealer_gex": gex,
            "dealer_delta": dealer_delta,
        }

    def record(self, snapshot):
        """Extract and append to the symbol's compact flow series. Returns the record or None."""
        rec = self.extract(snapshot)
        if not rec:
            return None
        self.OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = self.OUT_DIR / f"{rec['symbol']}.jsonl"
        # Dedup by timestamp so re-running the backfill is idempotent.
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip() and json.loads(line).get("ts") == rec["ts"]:
                    return rec
        with path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec
