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
    def _flow_rows(snapshot):
        sig = ((snapshot.get("providers") or {}).get("UNUSUAL_WHALES") or {}).get("signals") or {}
        fps = sig.get("flow_per_strike_intraday")
        if isinstance(fps, dict):
            return fps.get("data") or []
        return fps or []

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

        return {
            "ts": ts,
            "symbol": str(symbol).upper(),
            "call_ask_premium": round(call_ask, 2),
            "put_ask_premium": round(put_ask, 2),
            "net_premium": round(net_premium, 2),
            "directional_flow": round((call_ask - put_ask) / denom, 4),
            "flow_bias": "BULLISH" if call_ask > put_ask else "BEARISH",
            "strikes": len(rows),
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
