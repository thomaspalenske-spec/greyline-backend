import json
import re
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

    def _volume_flow(self, rows):
        """Ask-side call vs put VOLUME imbalance (breadth of aggressive buying).

        Distinct from directional_flow (premium-weighted): premium can be dominated by a
        few whales, volume counts how many aggressive trades lifted the offer. + = calls."""
        call = sum(self._f(r.get("call_volume_ask_side")) for r in rows)
        put = sum(self._f(r.get("put_volume_ask_side")) for r in rows)
        denom = call + put
        return round((call - put) / denom, 4) if denom else 0.0

    # --- provider-fed signals (real-time feeds not carried in the stored snapshot) ---
    # Fetched best-effort in record(); absent from historical backfill, they accumulate
    # forward from the day they were added. Both go through the provider's TTL cache and
    # budget governor, so this cannot hammer the API — and any failure just skips.

    _OPT_TYPE = re.compile(r"\d{6}([CP])\d")

    def _provider(self):
        if getattr(self, "_provider_instance", None) is None:
            from app.services.data_providers.unusual_whales_provider import UnusualWhalesProvider
            self._provider_instance = UnusualWhalesProvider()
        return self._provider_instance

    def _dark_pool_flow(self, symbol):
        """Net off-exchange (dark pool) premium imbalance vs the NBBO midpoint.

        The most direct read on institutional accumulation/distribution: dark prints have
        no buy/sell tag, so we infer aggressor from execution price vs the quote.
          price > mid -> buyer lifted toward the ask (accumulation, +)
          price < mid -> seller hit the bid (distribution, -)
        Returns net (buy-sell)/total premium in [-1, +1], or None if unavailable."""
        try:
            rows = self._rows(self._provider().dark_pool(symbol))
        except Exception:
            return None
        buy = sell = 0.0
        for r in rows:
            if r.get("canceled"):
                continue
            try:
                price = float(r["price"]); bid = float(r["nbbo_bid"]); ask = float(r["nbbo_ask"])
            except (TypeError, ValueError, KeyError):
                continue
            prem = self._f(r.get("premium"))
            mid = (bid + ask) / 2
            if price > mid:
                buy += prem
            elif price < mid:
                sell += prem
        denom = buy + sell
        return round((buy - sell) / denom, 4) if denom else None

    def _oi_flow(self, symbol):
        """Net directional open-interest change: new call OI vs new put OI.

        Distinguishes OPENING positioning (fresh institutional money) from intraday churn.
        + = OI building on calls (bullish accumulation), - = building on puts. Returns a
        signed ratio in [-1, +1], or None if unavailable."""
        try:
            rows = self._rows(self._provider().oi_change(symbol))
        except Exception:
            return None
        call = put = 0.0
        for r in rows:
            m = self._OPT_TYPE.search(str(r.get("option_symbol") or ""))
            if not m:
                continue
            v = self._f(r.get("oi_change") if r.get("oi_change") is not None else r.get("oi_diff_plain"))
            if m.group(1) == "C":
                call += v
            else:
                put += v
        denom = abs(call) + abs(put)
        return round((call - put) / denom, 4) if denom else None

    def _alert_flows(self, symbol):
        """Sweep and opening directional flow from UW flow alerts (one fetch, two reads).

        Both scope the same ask-side call-vs-put premium logic as directional_flow to a
        specific alert subset:
          sweep_flow   : SWEEP alerts — orders split across exchanges to fill fast, the
                         classic urgent-conviction footprint. + = bullish call sweeps.
          opening_flow : OPENING alerts — fresh positioning, not closing. The most direct
                         'new institutional money' read the mission is built to detect.
                         Opening = all_opening_trades flag OR volume > existing OI (the
                         flag is sparsely populated; vol/OI>1 is the robust proxy).
        Each in [-1, +1], or None if that subset is empty/unavailable."""
        try:
            rows = self._rows(self._provider().flow_alerts(symbol))
        except Exception:
            return None, None

        def _flow(subset):
            call = sum(self._f(r.get("total_ask_side_prem"))
                       for r in subset if str(r.get("type")).lower() == "call")
            put = sum(self._f(r.get("total_ask_side_prem"))
                      for r in subset if str(r.get("type")).lower() == "put")
            denom = call + put
            return round((call - put) / denom, 4) if denom else None

        def _is_opening(r):
            return bool(r.get("all_opening_trades")) or self._f(r.get("volume_oi_ratio")) > 1.0

        sweeps = [r for r in rows if r.get("has_sweep")]
        openings = [r for r in rows if _is_opening(r)]
        return _flow(sweeps), _flow(openings)

    def _enrich(self, rec):
        """Attach provider-fed real-time signals. Best-effort: must never break recording."""
        try:
            dp = self._dark_pool_flow(rec["symbol"])
            if dp is not None:
                rec["dark_pool_flow"] = dp
        except Exception:
            pass
        try:
            oi = self._oi_flow(rec["symbol"])
            if oi is not None:
                rec["oi_flow"] = oi
        except Exception:
            pass
        try:
            sweep, opening = self._alert_flows(rec["symbol"])
            if sweep is not None:
                rec["sweep_flow"] = sweep
            if opening is not None:
                rec["opening_flow"] = opening
        except Exception:
            pass

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
            "volume_flow": self._volume_flow(rows),
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
        self._enrich(rec)   # provider-fed signals only when actually recording a new snapshot
        with path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec
