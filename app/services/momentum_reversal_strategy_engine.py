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

    # Momentum's capital allocation. Default = the full book, but GREYLINE_MOMENTUM_CAPITAL_USD caps
    # it to a small sleeve: momentum is the strategy that lost 41% with no proven edge, so bounding
    # its deployment bounds its damage (per_name = CAPITAL_BASE / top_n, so a $1500 base = $150/name).
    CAPITAL_BASE = float(getenv("GREYLINE_MOMENTUM_CAPITAL_USD", "") or 10000.0)
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
        if capital_base is not None:
            self.capital_base = float(capital_base)       # explicit override (tests, callers)
        else:
            # %-of-equity budget: scales with the account instead of a static $ cap. A 0 budget
            # (no deployable cash) legitimately means "deploy nothing", so respect it (is-None, not
            # truthiness). Falls back to the static CAPITAL_BASE only if the resolver is unavailable.
            try:
                from app.services.sleeve_capital_budget_engine import SleeveCapitalBudgetEngine
                self.capital_base = SleeveCapitalBudgetEngine.budget_usd("momentum")
            except Exception:
                self.capital_base = self.CAPITAL_BASE
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
    def _excluded_symbols(self):
        """Names whose signal window is built on bars nobody actually traded.

        MIN_BARS only counts RAW bars, so a ticker carrying a long pre-listing stub (SW has
        16 years of ~$180/day prints) can satisfy 253 bars while offering almost no real
        history. Momentum computed across that boundary is measured against prices that
        never transacted. Fails open: no scan -> nothing excluded.
        """
        try:
            from app.services.price_bar_tradability_engine import PriceBarTradabilityEngine
            return PriceBarTradabilityEngine().contaminated_symbols()
        except Exception:
            return set()

    def _symbols(self):
        excluded = self._excluded_symbols()
        return sorted(s for s in (os.path.basename(p).replace("_daily.csv", "")
                                  for p in glob.glob(f"{self.HISTORICAL_DIR}/*_daily.csv"))
                      if s not in excluded)

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

    QUOTE_BATCH = 100          # TradeStation bulk-quotes accepts ~100 symbols per call

    def _bulk_quotes(self, symbols, base_url, token):
        """Current (date, close) per symbol via TradeStation BULK quotes.

        One HTTP call per QUOTE_BATCH symbols instead of one barchart call per symbol —
        ~50 calls for the whole NASDAQ vs ~5,000. This is the live tip; the 252 bars of
        history behind it don't change intraday and come from disk, so re-fetching them
        every cycle was the waste. Uses Last, falling back to Close then PreviousClose.
        """
        import requests as _rq
        out, headers = {}, {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        for i in range(0, len(symbols), self.QUOTE_BATCH):
            chunk = symbols[i:i + self.QUOTE_BATCH]
            try:
                r = _rq.get(base_url.rstrip("/") + "/v3/marketdata/quotes/" + ",".join(chunk),
                            headers=headers, timeout=30)
                if r.status_code != 200:
                    continue
                for q in (r.json() or {}).get("Quotes", []) or []:
                    sym = str(q.get("Symbol") or "").upper()
                    raw = q.get("Last") or q.get("Close") or q.get("PreviousClose")
                    try:
                        px = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if sym and px > 0:
                        out[sym] = (str(q.get("TradeTime") or "")[:10], px)
            except Exception:
                continue
        return out

    def _disk_history(self):
        """Per-symbol [(date, close)] from the on-disk CSVs — the immutable history, no API.

        These are kept current by the nightly bar refresh; the live quote adds today's tip.
        """
        hist = {}
        for p in glob.glob(f"{self.HISTORICAL_DIR}/*_daily.csv"):
            sym = os.path.basename(p).replace("_daily.csv", "").upper()
            closes = []
            try:
                with open(p) as f:
                    for r in csv.DictReader(f):
                        try:
                            closes.append((r["date"][:10], float(r["close"])))
                        except (ValueError, KeyError, TypeError):
                            pass
            except Exception:
                continue
            if closes:
                closes.sort(key=lambda x: x[0])
                hist[sym] = closes
        return hist

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

        # EFFICIENT LIVE FETCH: immutable history from disk + the live tip in bulk.
        #
        # The old path fetched a full 320-bar barchart PER SYMBOL every refresh — ~5,000
        # calls for the NASDAQ, and TradeStation caps concurrency near 2 req/s, so it was
        # both slow and API-hungry. But 252 of those 253 bars never change; only today's
        # bar is new. So history comes from the on-disk CSVs (kept current by the nightly
        # refresh, no API) and only the live tip is fetched — batched at ~100 symbols per
        # call. For the full NASDAQ that is ~50 calls instead of ~5,000, and it stays fully
        # live because the price driving each cycle's signal is today's real quote.
        history = self._disk_history()
        symbols = [s for s in self._symbols() if s.upper() in history]
        quotes = self._bulk_quotes(symbols, base_url, token)

        series, asof, failed = {}, None, []
        for sym in symbols:
            bars = history[sym.upper()]
            closes = [c for _, c in bars]
            last_date = bars[-1][0]
            q = quotes.get(sym.upper())
            # Append today's live close only if it is genuinely newer than the last stored
            # bar, so a stale quote or a repeated day never double-counts or back-dates.
            if q and q[0] and q[0] > last_date:
                closes = closes + [q[1]]
                day = q[0]
            else:
                day = last_date
            if len(closes) >= self.signal.MIN_BARS:
                series[sym] = closes
                if asof is None or day > asof:
                    asof = day
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
