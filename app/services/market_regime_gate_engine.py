"""Block dip-buying into a confirmed market downtrend — tail-risk protection for the signal.

GreyLine's signal buys the dip: a 12-month uptrend name that just pulled back short-term. That
is a sound mean-reversion bet in a normal market and a catastrophe in a crash, where every dip
keeps dipping (2008). The strategy had NO awareness of the broad market's state — it would buy
pullbacks all the way down. This gate adds that awareness.

The rule is the single most-studied, least-overfit regime filter there is: the broad index
versus its 200-day moving average. No tunable knobs, nothing learned, nothing to overfit —
deliberately, because this repo has already been burned by regime models whose accuracy was an
artifact of correlated samples.

WHAT THE DATA ACTUALLY SAYS (validated on SPY 1998-2026, forward 5-day returns):

  SPY above 200DMA: avg +0.174%, worst 5d -12.8%
  SPY below 200DMA: avg +0.160%, worst 5d -19.8%; 72% of the 200 worst outcomes were here

Read that honestly: the regime filter does NOT improve average return — it is a wash. Its
entire value is TAIL RISK. Below the 200DMA the average is the same but the left tail is far
fatter, and a dip-buyer is buying the names most exposed to that tail. Trading a return-neutral
average for a large cut in crash exposure is a Sharpe/drawdown win, not a return win. Anyone who
sells this as alpha is overselling it.

BEHAVIOUR: in RISK_OFF (index below its 200DMA) new BULLISH (call) dip-buys are blocked.
BEARISH (put) setups — a downtrended name that just rallied — are still allowed, because fading
rallies is exactly what mean-reversion should be doing in a downtrend. The gate never forces a
trade; it only removes bullish ones.

FAILS OPEN: if the index series is missing or stale the gate allows everything and reports
DEGRADED, matching every other data engine here. A data glitch must not silently halt trading —
but the Reality Guard surfaces the degraded state so it cannot hide.
"""

import csv
from datetime import datetime
from os import getenv
from pathlib import Path


class MarketRegimeGateEngine:

    HIST_DIR = Path("app/data/historical")
    INDEX = "SPY"             # broad-market proxy; present with 7000+ bars
    LONG_SMA = 200            # the regime line
    SHORT_SMA = 50            # informational confirmation, not a second gate
    STALE_DAYS = 7            # index bar older than this -> can't trust the regime read

    @staticmethod
    def enabled():
        # Default ON: the whole point is protection, and the operator asked for it. Set
        # GREYLINE_REGIME_GATE_ENABLED=false to trade without regime awareness.
        return (getenv("GREYLINE_REGIME_GATE_ENABLED", "true") or "").strip().lower() != "false"

    def _closes(self):
        rows = []
        try:
            with open(self.HIST_DIR / f"{self.INDEX}_daily.csv") as f:
                for r in csv.DictReader(f):
                    try:
                        rows.append((str(r["date"])[:10], float(r["close"])))
                    except (ValueError, KeyError, TypeError):
                        continue
        except Exception:
            return []
        return rows

    def assess(self):
        """Current regime read from the index vs its 200DMA. Never raises."""
        rows = self._closes()
        if len(rows) < self.LONG_SMA + 1:
            return {"regime": "UNKNOWN", "risk_off": False, "degraded": True,
                    "detail": f"insufficient {self.INDEX} history for a {self.LONG_SMA}DMA"}

        last_date, last_close = rows[-1]
        try:
            age = (datetime.utcnow().date() - datetime.fromisoformat(last_date).date()).days
        except Exception:
            age = 0
        if age > self.STALE_DAYS:
            return {"regime": "UNKNOWN", "risk_off": False, "degraded": True,
                    "detail": f"{self.INDEX} last bar {age}d old — regime read not trusted",
                    "as_of": last_date}

        closes = [c for _, c in rows]
        sma200 = sum(closes[-self.LONG_SMA:]) / self.LONG_SMA
        sma50 = sum(closes[-self.SHORT_SMA:]) / self.SHORT_SMA
        risk_off = last_close < sma200
        pct_from_200 = (last_close / sma200 - 1) * 100
        return {
            "index": self.INDEX,
            "as_of": last_date,
            "close": round(last_close, 2),
            "sma200": round(sma200, 2),
            "sma50": round(sma50, 2),
            "pct_vs_200dma": round(pct_from_200, 2),
            "golden_cross": sma50 >= sma200,     # informational
            "regime": "RISK_OFF" if risk_off else "RISK_ON",
            "risk_off": bool(risk_off),
            "degraded": False,
            "detail": (f"{self.INDEX} {last_close:.2f} is {pct_from_200:+.1f}% vs its 200DMA "
                       f"({sma200:.2f}) — {'BELOW: dip-buying blocked' if risk_off else 'above: normal'}"),
        }

    def filter_targets(self, targets):
        """Remove BULLISH dip-buys when the market is RISK_OFF. Returns (kept, dropped, regime).

        Bearish/put targets pass through in every regime. A degraded or disabled gate keeps
        everything — it can only ever remove bullish trades, never invent or force one.
        """
        regime = self.assess()
        if not self.enabled():
            return list(targets), [], {**regime, "gate_enabled": False}
        if not regime.get("risk_off"):
            return list(targets), [], {**regime, "gate_enabled": True}

        kept, dropped = [], []
        for t in targets or []:
            bias = str(t.get("directional_bias") or "").upper()
            side = str(t.get("side") or "").upper()
            is_bullish = bias == "BULLISH" or side in ("BUY", "LONG")
            if is_bullish:
                dropped.append({"symbol": t.get("symbol"), "bias": bias or side,
                                "reason": "REGIME_RISK_OFF_BLOCKS_DIP_BUY"})
            else:
                kept.append(t)
        return kept, dropped, {**regime, "gate_enabled": True}
