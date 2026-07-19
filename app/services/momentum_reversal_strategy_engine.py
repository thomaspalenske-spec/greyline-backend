import bisect
import csv
import glob
import hashlib
import json
import os
from datetime import datetime
from os import getenv
from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor

from app.services.directional_signal_engine import DirectionalSignalEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.position_exposure_limit_engine import PositionExposureLimitEngine
from app.services.tradestation_token_maintenance_engine import (
    TradeStationTokenMaintenanceEngine,
)


class MomentumReversalStrategyEngine:
    """
    The rebuilt, validated strategy wired to the paper chassis.

    Signal: DirectionalSignalEngine (12-1 momentum AND 5-day reversal must agree) — the
    only directional core that beat a coin flip out-of-sample over 28 years. Traded as
    EQUITY / delta-1 (not options), because the edge is thin (~0.23%/5d) and would be
    eaten by option premium and theta.

    Deployment: each rebalance, score the universe, rank the CONFIRMED signals by
    conviction (|momentum| + |reversal move|), and hold the top-N — which matches a small
    account and cuts the turnover that was killing net returns.

    Honest status: backtests validated the SIGNAL and the STRUCTURE, but their magnitude
    is survivorship-biased (the CSV universe is today's winners). This exists to trade it
    FORWARD on real data, where that bias doesn't exist, and let the fixed-horizon grader
    and data-integrity pipeline measure the true edge.
    """

    CAPITAL_BASE = 10000.0
    # Breadth. A thin edge only survives diversification (the portfolio backtest showed it
    # emerges in a basket, not a single name), and more names per rebalance is also the
    # only lever on time-to-verdict: 30 closed trades is ~6 weeks at 5/week, ~3 at 10.
    TOP_N = 10
    HISTORICAL_DIR = "app/data/historical"

    # Round-trip transaction cost (spread + slippage; retail commissions are ~0).
    # NOT cosmetic: the backtest's out-of-sample Sharpe went 0.42 gross -> 0.25 @5bps ->
    # 0.08 @10bps. A verdict computed on frictionless fills would be fantasy, so 10bps is
    # the conservative default and the track record is judged net of it.
    COST_BPS_ROUND_TRIP = float(getenv("GREYLINE_COST_BPS_ROUND_TRIP", "10"))
    LIVE_CACHE = Path("app/data/price_history/live_universe_cache.json")
    LIVE_BARS_BACK = 320          # ~14 months of daily bars, > the 253 the signal needs
    # 13h, not 6h: at 6h a cache warmed before the 08:30 CDT open expires around 14:00,
    # forcing a multi-minute refetch of the whole S&P 500 mid-session. 13h lets one
    # pre-open warm cover the entire trading day. Bars are DAILY, so an intraday-aged
    # cache holds the same closes either way; the data-quality gate that actually
    # matters is _staleness(), which checks the latest BAR date, not the cache age.
    CACHE_TTL_SECONDS = 13 * 3600
    FETCH_WORKERS = 8             # TradeStation throttles ~2 req/s regardless; see _live_universe

    def __init__(self, top_n=None, capital_base=None):
        self.top_n = int(top_n) if top_n else self.TOP_N
        self.capital_base = float(capital_base) if capital_base else self.CAPITAL_BASE
        self.signal = DirectionalSignalEngine()

    # --- selection (pure; the alpha logic) -------------------------------------
    def select(self, universe_series):
        """universe_series: {symbol: [closes oldest->newest]} -> (top_n targets, all confirmed)."""
        confirmed = []
        for sym, closes in universe_series.items():
            sig = self.signal.evaluate(closes)
            if not sig.get("tradeable"):
                continue
            confirmed.append({
                "symbol": sym,
                "directional_bias": sig["directional_bias"],
                "side": "BUY" if sig["directional_bias"] == "BULLISH" else "SELL",
                "momentum_12_1_pct": sig["momentum_12_1_pct"],
                "reversal_5d_move_pct": sig["reversal_5d_move_pct"],
                "last_close": closes[-1],
            })

        # Conviction = cross-sectional RANK of each leg's magnitude, summed. Raw
        # magnitude let 12-month momentum (hundreds of %) drown the reversal leg
        # (single-digit %), collapsing the combo into naive momentum and concentrating
        # in extreme, crash-prone high-flyers. Percentile rank bounds each leg to [0,1]
        # so both contribute equally — a name needs strong momentum AND strong reversal
        # to rank top, which is the whole point of requiring them to agree.
        if confirmed:
            moms = sorted(abs(c["momentum_12_1_pct"]) for c in confirmed)
            revs = sorted(abs(c["reversal_5d_move_pct"]) for c in confirmed)
            n = len(confirmed)
            for c in confirmed:
                mr = bisect.bisect_right(moms, abs(c["momentum_12_1_pct"])) / n
                rr = bisect.bisect_right(revs, abs(c["reversal_5d_move_pct"])) / n
                c["conviction"] = round(mr + rr, 4)
                c["momentum_rank"] = round(mr, 3)
                c["reversal_rank"] = round(rr, 3)

        confirmed.sort(key=lambda x: x.get("conviction", 0), reverse=True)
        return confirmed[:self.top_n], confirmed

    # --- data feed -------------------------------------------------------------
    def _symbols(self):
        return sorted(os.path.basename(p).replace("_daily.csv", "")
                      for p in glob.glob(f"{self.HISTORICAL_DIR}/*_daily.csv"))

    def _csv_universe(self):
        series, asof = {}, None
        for p in sorted(glob.glob(f"{self.HISTORICAL_DIR}/*_daily.csv")):
            sym = os.path.basename(p).replace("_daily.csv", "")
            closes, last = [], None
            with open(p) as f:
                for r in csv.DictReader(f):
                    try:
                        closes.append(float(r["close"]))
                        last = r["date"][:10]
                    except (ValueError, KeyError, TypeError):
                        pass
            if len(closes) >= self.signal.MIN_BARS:
                series[sym] = closes
                if last and (asof is None or last > asof):
                    asof = last
        return series, asof, "HISTORICAL_CSV"

    def _fetch_daily_closes(self, symbol, base_url, token):
        """Current daily closes (oldest->newest) from TradeStation BarCharts, or []."""
        url = base_url.rstrip("/") + f"/v3/marketdata/barcharts/{symbol}"
        resp = requests.get(
            url,
            params={"unit": "Daily", "barsback": self.LIVE_BARS_BACK},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        bars = (resp.json() or {}).get("Bars", []) or []
        out = []
        for b in bars:
            ts = b.get("TimeStamp") or b.get("Timestamp")
            c = b.get("Close")
            try:
                c = float(c)
            except (TypeError, ValueError):
                continue
            if ts and c > 0:
                out.append((str(ts)[:10], c))
        out.sort(key=lambda x: x[0])
        return out

    def _universe_key(self):
        """Identity of the symbol set the cache was built from."""
        return hashlib.sha256("|".join(self._symbols()).encode()).hexdigest()[:16]

    def _live_universe(self):
        # Serve from cache if fresh AND built from the same symbol set. Age alone is not
        # enough: expanding the universe from 98 names to the S&P 500 left a young cache
        # holding the OLD 98 series, so the strategy would have gone on selecting from the
        # old universe until the TTL happened to lapse — the expansion silently doing
        # nothing. Keying on the symbol set makes a universe change invalidate the cache
        # immediately, which is the only behaviour that cannot quietly mislead.
        if self.LIVE_CACHE.exists():
            try:
                cached = json.loads(self.LIVE_CACHE.read_text())
                age = (datetime.utcnow() - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
                if (age < self.CACHE_TTL_SECONDS and cached.get("series")
                        and cached.get("universe_key") == self._universe_key()):
                    return cached["series"], cached.get("as_of"), "TRADESTATION_LIVE_CACHED"
            except Exception:
                pass

        TradeStationTokenMaintenanceEngine().evaluate()   # refresh access token
        token = getenv("TRADESTATION_ACCESS_TOKEN", "")
        base_url = getenv("TRADESTATION_SANDBOX_URL", "https://sim-api.tradestation.com")
        if not token:
            raise RuntimeError("no TradeStation access token")

        # Fetched concurrently: the universe is the whole S&P 500, and serially that is ~8
        # minutes of blocking inside rebalance() at the open — against an entry doctrine
        # that validated MARKET entry precisely because delay adversely selects.
        # TradeStation throttles server-side around 2 requests/sec no matter how many
        # workers we use (measured: 1 worker 1.1/s, 6 workers 1.9/s, 12 workers 2.1/s with
        # zero errors), so this roughly halves the wall time and no more. The real
        # protection is a cache warmed before the open — see CACHE_TTL_SECONDS.
        series, asof, failed = {}, None, []

        def _one(sym):
            try:
                return sym, self._fetch_daily_closes(sym, base_url, token)
            except Exception:
                return sym, None

        with ThreadPoolExecutor(max_workers=self.FETCH_WORKERS) as pool:
            for sym, bars in pool.map(_one, self._symbols()):
                if bars is None:
                    failed.append(sym)
                    continue
                closes = [c for _, c in bars]
                if len(closes) >= self.signal.MIN_BARS:
                    series[sym] = closes
                    last = bars[-1][0]
                    if last and (asof is None or last > asof):
                        asof = last
                else:
                    failed.append(sym)

        if not series:
            raise RuntimeError("live fetch produced no usable series")

        self.LIVE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        self.LIVE_CACHE.write_text(json.dumps(
            {"fetched_at": datetime.utcnow().isoformat(), "as_of": asof,
             "universe_key": self._universe_key(), "symbols": len(self._symbols()),
             "failed": failed, "series": series}))
        return series, asof, "TRADESTATION_LIVE"

    def universe(self, prefer_live=True):
        # Live daily bars (series ends today) with a per-run cache; fall back to the deep
        # CSV history if the live feed is unavailable, reporting the source honestly.
        if prefer_live:
            try:
                return self._live_universe()
            except Exception:
                pass
        return self._csv_universe()

    # --- recommendation (dry run; no trades) -----------------------------------
    def run(self):
        series, asof, source = self.universe()
        targets, confirmed = self.select(series)
        per_name = self.capital_base / self.top_n if self.top_n else 0
        for t in targets:
            t["target_notional"] = round(per_name, 2)
            # Fractional. Integer truncation silently dropped any name priced above the
            # per-name budget (LLY at $1,142 was skipped outright) — a price bias the
            # backtest never had, since it weighted exactly. Fractional sizing removes it.
            t["target_quantity"] = round(per_name / t["last_close"], 4) if t["last_close"] > 0 else 0
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "MomentumReversalStrategyEngine",
            "as_of": asof,
            "data_source": source,
            "universe_size": len(series),
            "confirmed_signals": len(confirmed),
            "top_n": self.top_n,
            "capital_base": self.capital_base,
            "targets": targets,
            "note": ("Validated 12-1 momentum + 5-day reversal, traded as equity. "
                     "Live production should feed current daily bars."),
            "status": "MOMENTUM_REVERSAL_STRATEGY_READY",
        }

    # --- execution (records paper trades; gated + risk-checked) ----------------
    def record_paper_trades(self, ledger=None):
        if (getenv("GREYLINE_PAPER_EXECUTION_ENABLED", "") or "").lower() != "true":
            return {"recorded": 0, "reason": "PAPER_EXECUTION_DISABLED",
                    "status": "MOMENTUM_REVERSAL_EXECUTION_BLOCKED"}

        limits = PositionExposureLimitEngine().evaluate()
        if not limits.get("limits_ok"):
            return {"recorded": 0, "reason": "RISK_LIMIT_BLOCK",
                    "breaches": limits.get("breaches"),
                    "status": "MOMENTUM_REVERSAL_EXECUTION_RISK_BLOCKED"}

        plan = self.run()
        led = ledger or PaperTradeLedgerEngine()
        recorded = []
        for t in plan["targets"]:
            if t["target_quantity"] <= 0:
                continue
            led.open_trade(
                symbol=t["symbol"],
                side=t["side"],
                quantity=t["target_quantity"],
                entry_price=t["last_close"],
                directional_bias=t["directional_bias"],
                trade_intent="MOMENTUM_REVERSAL",
                direction_confidence=t["conviction"],
            )
            recorded.append({"symbol": t["symbol"], "side": t["side"],
                             "quantity": t["target_quantity"], "entry_price": t["last_close"]})
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "MomentumReversalStrategyEngine",
            "recorded": len(recorded),
            "as_of": plan["as_of"],
            "trades": recorded,
            "status": "MOMENTUM_REVERSAL_EXECUTION_COMPLETE",
        }
