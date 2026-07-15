import bisect
import csv
import glob
import os
from datetime import datetime
from os import getenv

from app.services.directional_signal_engine import DirectionalSignalEngine
from app.services.paper_trade_ledger_engine import PaperTradeLedgerEngine
from app.services.position_exposure_limit_engine import PositionExposureLimitEngine


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
    TOP_N = 5
    HISTORICAL_DIR = "app/data/historical"

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

    def universe(self):
        # Production should prepend a live TradeStation daily-bars fetch (fetch_bars in
        # backfill_price_history.py) so the series ends today. Absent a token, the deep
        # CSV history is used and the as-of date is reported honestly.
        return self._csv_universe()

    # --- recommendation (dry run; no trades) -----------------------------------
    def run(self):
        series, asof, source = self.universe()
        targets, confirmed = self.select(series)
        per_name = self.capital_base / self.top_n if self.top_n else 0
        for t in targets:
            t["target_notional"] = round(per_name, 2)
            t["target_quantity"] = int(per_name / t["last_close"]) if t["last_close"] > 0 else 0
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
