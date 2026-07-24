"""Capture options reality daily — because none of it can be recovered afterwards.

GreyLine's mission is to profit trading OPTIONS, and the binding constraint is that an options
edge CANNOT BE BACKTESTED here. Verified: UW's `/api/option-contract/{id}/historic` describes
exactly the per-day contract OHLC + IV we would need, but returns ZERO rows for every contract
tested — including live SPY contracts with 340k daily volume pulled from UW's own chain.
TradeStation purges expired contracts entirely. There is no historical options dataset to buy
our way out of with the tools we have.

So the only path to a verifiable options edge is FORWARD: start recording the option surface
now and test hypotheses against the accumulating panel in weeks. Every day not captured is
evidence that does not exist later — the same lesson survivorship taught, applied to options.
That is why this engine treats a missed day as a real failure and says so loudly.

WHAT IS CAPTURED (per underlying, per day), all options-native:
  * volatility surface  — iv30d and its 1d/1w/1m changes, iv_rank, realized_volatility,
                          volatility_7/30
  * VARIANCE RISK PREMIUM — IV richness over realized. The most replicated options edge in the
                          literature and the strongest candidate our data supports.
  * expected move       — implied_move and implied_move_perc (7/30d), against next_earnings_date
  * dealer positioning  — gex_ratio, gex_net_change, gex_perc_change
  * flow                — call/put volume and premium, net call/put premium, put_call_ratio
  * open interest       — call/put/total OI and prior-day OI
Sourced from UW's stock screener, which returns all of it in bulk (500 rows/request), walked in
market-cap bands because its `page` parameter does not work.

Storage is one append-only JSONL per day. Days are never overwritten and never merged: a
capture either exists for a date or it does not, which keeps the panel auditable.
"""

import json
from datetime import datetime
from os import getenv
from pathlib import Path

import requests


class OptionsRealityCaptureEngine:

    SCREENER = "https://api.unusualwhales.com/api/screener/stocks"
    OUT_DIR = Path("app/data/options_reality")
    PAGE = 500
    MAX_BANDS = 12          # ~6,000 names walked; options liquidity concentrates far above this

    # The options-native fields worth keeping. Everything here is a potential filter input;
    # nothing is a judgement about a name.
    FIELDS = [
        "ticker", "date", "close", "prev_close", "sector", "issue_type", "marketcap",
        # volatility surface
        "iv30d", "iv30d_1d", "iv30d_1w", "iv30d_1m", "iv_rank",
        "realized_volatility", "volatility", "volatility_7", "volatility_30",
        "variance_risk_premium",
        # expected move / events
        "implied_move", "implied_move_perc", "implied_move_7", "implied_move_30",
        "next_earnings_date", "er_time",
        # dealer positioning
        "gex_ratio", "gex_net_change", "gex_perc_change",
        # flow
        "call_volume", "put_volume", "call_premium", "put_premium",
        "net_call_premium", "net_put_premium", "put_call_ratio",
        "call_volume_ask_side", "call_volume_bid_side",
        "put_volume_ask_side", "put_volume_bid_side",
        # open interest
        "call_open_interest", "put_open_interest", "total_open_interest",
        "prev_call_oi", "prev_put_oi",
        # liquidity context
        "stock_volume", "avg30_volume", "avg_30_day_call_volume", "avg_30_day_put_volume",
    ]

    def _headers(self):
        return {"Authorization": f"Bearer {getenv('UNUSUAL_WHALES_API_KEY')}",
                "Accept": "application/json"}

    @staticmethod
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _band(self, max_cap=None):
        params = {"limit": self.PAGE, "order": "marketcap", "order_direction": "desc"}
        if max_cap:
            params["max_marketcap"] = int(max_cap)
        try:
            r = requests.get(self.SCREENER, params=params, headers=self._headers(), timeout=60)
            if r.status_code != 200:
                return [], f"HTTP {r.status_code}"
            return ((r.json() or {}).get("data") or []), None
        except Exception as e:
            return [], str(e)[:80]

    def path_for(self, day):
        return self.OUT_DIR / f"options_surface_{day}.jsonl"

    def capture(self, day=None, overwrite=False):
        day = day or datetime.utcnow().date().isoformat()
        out_path = self.path_for(day)
        if out_path.exists() and not overwrite:
            n = sum(1 for l in out_path.read_text().splitlines() if l.strip())
            return {"status": "ALREADY_CAPTURED_TODAY", "date": day, "rows": n, "captured": False}

        seen, rows, errors = set(), [], []
        max_cap = None
        for _ in range(self.MAX_BANDS):
            band, err = self._band(max_cap)
            if err:
                errors.append(err)
                break
            if not band:
                break
            caps = [self._f(x.get("marketcap")) for x in band]
            caps = [c for c in caps if c and c > 0]
            for x in band:
                t = str(x.get("ticker") or "").upper()
                if not t or t in seen:
                    continue
                seen.add(t)
                rec = {k: x.get(k) for k in self.FIELDS if k in x}
                rec["ticker"] = t
                rec["capture_date"] = day
                rows.append(rec)
            if not caps:
                break
            nxt = min(caps)
            if max_cap is not None and nxt >= max_cap:
                break
            max_cap = nxt

        if not rows:
            # A day with no capture is unrecoverable — never pretend it succeeded.
            return {"status": "CAPTURE_FAILED_NO_ROWS", "date": day, "rows": 0,
                    "captured": False, "errors": errors[:3],
                    "detail": "no options surface recorded for this date — the data for this "
                              "day cannot be reconstructed later"}

        try:
            self.OUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
        except Exception as e:
            return {"status": "CAPTURE_WRITE_FAILED", "date": day, "error": str(e)[:120],
                    "captured": False}

        with_vrp = sum(1 for r in rows if self._f(r.get("variance_risk_premium")) is not None)
        with_iv = sum(1 for r in rows if self._f(r.get("iv30d")) is not None)
        return {
            "status": "OPTIONS_SURFACE_CAPTURED", "captured": True, "date": day,
            "rows": len(rows), "with_iv30d": with_iv, "with_variance_risk_premium": with_vrp,
            "file": str(out_path), "errors": errors[:3],
        }

    def coverage(self):
        """What the accumulating panel actually contains — the basis for forward testing."""
        try:
            files = sorted(self.OUT_DIR.glob("options_surface_*.jsonl"))
        except Exception:
            files = []
        days = [f.name.replace("options_surface_", "").replace(".jsonl", "") for f in files]
        total = 0
        for f in files:
            try:
                total += sum(1 for l in f.read_text().splitlines() if l.strip())
            except Exception:
                pass
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "days_captured": len(days),
            "first_day": days[0] if days else None,
            "last_day": days[-1] if days else None,
            "total_rows": total,
            "note": ("Options edges cannot be backtested — UW's historic-contract endpoint "
                     "returns nothing and TradeStation purges expired contracts. This panel is "
                     "the ONLY basis for verifying an options hypothesis, and it only grows "
                     "forward. A missed day is permanently missing."),
            "status": "OPTIONS_CAPTURE_COVERAGE",
        }

    def capture_if_due(self):
        """Safe to call every scheduler cycle — one capture per calendar day."""
        day = datetime.utcnow().date().isoformat()
        if self.path_for(day).exists():
            return {"status": "ALREADY_CAPTURED_TODAY", "date": day, "captured": False}
        return self.capture(day)
