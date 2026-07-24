"""Find where each symbol's history becomes genuinely TRADABLE — and flag what comes before.

A price series can be clean, self-consistent, and match the vendor exactly, and still be
unusable: many tickers carry long pre-listing stubs. Smurfit Westrock's file starts in 2008
but the company only began trading in the US in July 2024, so ~16 years of "history" are
near-untraded prints. Ferrovial: 80% of its bars trade under 1,000 shares.

Those bars are poison in two distinct ways:

  BACKTESTS  a frozen, zero-volume stretch has no volatility and no slippage. It manufactures
             clean-looking momentum and reversal patterns that could never have been traded.
             This is a textbook fake-edge trap — the same family as the overlap and
             multiple-comparison errors that already killed the flow-edge hypothesis.
  LIVE       the 12-1 signal reads 253 bars back. If that window reaches into a stub, the
             momentum leg is computed from prices nobody transacted at, and ATR collapses —
             which shrinks every doctrine stop derived from it.

Tradability is judged by DOLLAR VOLUME against a fixed floor, which separates "small but
genuinely traded" from "not traded at all" without penalising symbols whose volume grew over
25 years. See DOLLAR_VOLUME_FLOOR for why the relative-to-recent-median test was wrong.
"""

import csv
import json
from datetime import datetime
from pathlib import Path


class PriceBarTradabilityEngine:

    HIST_DIR = Path("app/data/historical")
    OUT = Path("app/data/data_quality/price_bar_tradability.json")

    # Judge bars by DOLLAR VOLUME against an absolute floor — not by share count, and not
    # relative to the symbol's own recent volume.
    #
    # The relative test was wrong and I had it in first: measuring each bar against 1% of the
    # RECENT median penalises any symbol whose volume grew over 25 years. It flagged XLE, XLP,
    # XLV and XLI as having ~18% "untradable" history, when those sector ETFs traded millions
    # of dollars a day in 1999 — they were simply smaller then than now. Dollar volume against
    # a fixed floor separates "small but genuinely traded" from "not traded at all":
    #   SW pre-2024   ~6 sh x $30    = ~$180/day      -> untradable, correctly
    #   XLE in 1999   ~100k sh x $25 = ~$2.5M/day     -> tradable, correctly
    DOLLAR_VOLUME_FLOOR = 250_000
    SUSTAIN_DAYS = 20         # consecutive tradable bars before we call liquidity established
    SIGNAL_BARS = 253         # what the 12-1 momentum signal actually reads
    PREFIX_ALERT_PCT = 10.0   # report symbols whose untradable prefix exceeds this share

    def _rows(self, path):
        out = []
        try:
            with open(path) as f:
                for r in csv.DictReader(f):
                    try:
                        out.append((str(r["date"])[:10], float(r["close"]),
                                    float(r.get("volume") or 0)))
                    except (ValueError, KeyError, TypeError):
                        continue
        except Exception:
            return []
        return out

    @staticmethod
    def _dollar_volume(close, volume):
        return float(close or 0) * float(volume or 0)

    def analyze_symbol(self, symbol, rows=None):
        rows = rows if rows is not None else self._rows(self.HIST_DIR / f"{symbol}_daily.csv")
        if not rows:
            return None
        thresh = self.DOLLAR_VOLUME_FLOOR
        n = len(rows)

        # First index from which SUSTAIN_DAYS consecutive bars all clear the bar. Anything
        # before it is a stub: listed-elsewhere, pre-IPO placeholder, or simply not traded.
        first_ok = None
        streak = 0
        for i, (_, c, v) in enumerate(rows):
            if self._dollar_volume(c, v) >= thresh:
                streak += 1
                if streak >= self.SUSTAIN_DAYS:
                    first_ok = i - self.SUSTAIN_DAYS + 1
                    break
            else:
                streak = 0
        if first_ok is None:
            first_ok = n            # never established liquidity

        untradable_prefix = first_ok
        signal_start = max(0, n - self.SIGNAL_BARS)
        return {
            "symbol": symbol,
            "bars": n,
            "first_date": rows[0][0],
            "last_date": rows[-1][0],
            "dollar_volume_floor": thresh,
            "tradable_from": rows[first_ok][0] if first_ok < n else None,
            "untradable_prefix_bars": untradable_prefix,
            "untradable_prefix_pct": round(untradable_prefix / n * 100, 1) if n else 0.0,
            # THE live-risk question: does the window the signal actually reads reach back
            # into the stub? If so, this symbol's momentum leg is built on untraded prints.
            "stub_inside_signal_window": bool(first_ok > signal_start),
            "usable_signal_bars": max(0, n - max(first_ok, signal_start)),
        }

    def scan(self, save=True):
        results = []
        for p in sorted(self.HIST_DIR.glob("*_daily.csv")):
            sym = p.name.replace("_daily.csv", "")
            r = self.analyze_symbol(sym, self._rows(p))
            if r:
                results.append(r)

        contaminated = [r for r in results if r["stub_inside_signal_window"]]
        stubby = [r for r in results
                  if r["untradable_prefix_pct"] >= self.PREFIX_ALERT_PCT]
        never = [r for r in results if r["tradable_from"] is None]

        out = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols": len(results),
            "signal_bars": self.SIGNAL_BARS,
            # live trading risk
            "contaminated_signal_windows": len(contaminated),
            "contaminated": sorted(contaminated,
                                   key=lambda r: -r["untradable_prefix_pct"])[:40],
            # backtest / research risk
            "symbols_with_large_stub": len(stubby),
            "large_stubs": sorted(stubby, key=lambda r: -r["untradable_prefix_pct"])[:40],
            "never_liquid": [r["symbol"] for r in never],
            "ok": len(contaminated) == 0,
            "status": ("TRADABILITY_CLEAN_FOR_SIGNALS" if not contaminated
                       else "SIGNAL_WINDOW_CONTAMINATED_BY_UNTRADED_BARS"),
        }
        if save:
            try:
                self.OUT.parent.mkdir(parents=True, exist_ok=True)
                self.OUT.write_text(json.dumps(out, indent=2))
            except Exception:
                pass
        return out

    def contaminated_symbols(self):
        """Symbols whose 253-bar signal window reaches into an untraded stub.

        The strategy excludes these. Returns an EMPTY set when no scan exists, so a missing
        or stale scan degrades to today's behaviour rather than silently emptying the
        universe — a data-quality file must never be able to halt trading by its absence.
        """
        data = self.last_scan() or {}
        return {r.get("symbol") for r in (data.get("contaminated") or []) if r.get("symbol")}

    def tradable_from_map(self):
        """{symbol: first tradable date} — for backtests to clip pre-liquidity bars."""
        try:
            data = json.loads(self.OUT.read_text())
        except Exception:
            return {}
        out = {}
        for key in ("contaminated", "large_stubs"):
            for r in data.get(key) or []:
                if r.get("tradable_from"):
                    out[r["symbol"]] = r["tradable_from"]
        return out

    def last_scan(self):
        try:
            return json.loads(self.OUT.read_text())
        except Exception:
            return None
