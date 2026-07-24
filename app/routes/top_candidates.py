"""Top candidates from the REAL, validated strategy — momentum-reversal on the live universe.

This is the same engine that ranks (and would trade) actual positions: DirectionalSignalEngine
requires 12-1 momentum AND 5-day reversal to agree, conviction is the percentile-rank blend of
the two legs. Every number here is computed from real daily price data (live TradeStation feed,
falling back to same-day cached bars), not a retired coin-flip signal.

TTL-cached (15 min): a full run scores ~550 names in a few seconds, far too heavy for the
dashboard's 15s refresh. The cache serves instantly; a miss recomputes inline. `as_of` and
`data_source` are surfaced so the panel can honestly show how fresh the data is.
"""

import json
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from app.services.momentum_reversal_strategy_engine import MomentumReversalStrategyEngine

router = APIRouter()

CACHE = Path("app/data/momentum_reversal/top_candidates_cache.json")
TTL_SECONDS = 900  # 15 min


def _compute(top_n):
    strat = MomentumReversalStrategyEngine(top_n=top_n)
    series, asof, source = strat.universe()
    targets, confirmed = strat.select(series)   # confirmed = the full ranked list

    candidates = []
    for i, t in enumerate(targets[:top_n], start=1):
        candidates.append({
            "rank": i,
            "symbol": t.get("symbol"),
            "side": t.get("side"),
            "direction": "LONG" if t.get("side") == "BUY" else "SHORT",
            "directional_bias": t.get("directional_bias"),
            "conviction": t.get("conviction"),
            "momentum_rank": t.get("momentum_rank"),
            "reversal_rank": t.get("reversal_rank"),
            "momentum_12_1_pct": round(float(t.get("momentum_12_1_pct") or 0), 1),
            "reversal_5d_move_pct": round(float(t.get("reversal_5d_move_pct") or 0), 1),
            "last_close": t.get("last_close"),
        })

    # Contract board: the single TOP-scoring contract (affordable or not) + the top-5
    # affordable contracts, scored by GreyLine's OI/delta ranking over a wider ranked pool.
    #
    # Contract scoring needs LIVE STREAMING option quotes, which only flow during the regular
    # session. When the options market is closed the streaming chain endpoint hangs and ends
    # the connection prematurely — a ~20s-per-name stall for nothing. So gate on market hours:
    # when closed, skip the fetch and say so honestly. The signal side above is fully computed
    # regardless (it runs off daily bars), so the candidates still populate; only the option
    # contract columns wait for the open.
    board = {"top_scoring_contract": None, "affordable_contracts": [], "scanned": 0}
    try:
        from app.services.market_hours_engine import MarketHoursEngine
        if MarketHoursEngine().status().get("is_regular_session") is not True:
            board = {"top_scoring_contract": None, "affordable_contracts": [],
                     "status": "OPTIONS_MARKET_CLOSED",
                     "detail": "contract scoring resumes at market open (live option quotes stream only during the session)"}
        else:
            from app.services.momentum_options_execution_engine import MomentumOptionsExecutionEngine
            oeng = MomentumOptionsExecutionEngine()
            board = oeng.contract_board(confirmed, oeng._free_cash(), pool=10, top_affordable=5)
    except Exception as e:
        board = {"top_scoring_contract": None, "affordable_contracts": [], "error": str(e)[:150]}

    return {
        "computed_at": datetime.utcnow().isoformat(),
        "computed_epoch": time.time(),
        "as_of": asof,
        "data_source": source,
        "universe_size": len(series),
        "confirmed_signals": len(confirmed),
        "candidates": candidates,
        "contract_board": board,
        "engine": "MomentumReversalStrategyEngine",
        "signal": "12-1 momentum AND 5-day reversal must agree; conviction = percentile-rank blend",
        "status": "TOP_CANDIDATES_READY",
    }


@router.get("/top-candidates")
def top_candidates(force: bool = False, top_n: int = 5):
    """Top-N momentum-reversal candidates, TTL-cached. ?force=true recomputes now."""
    if not force and CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text())
            fresh = (time.time() - float(cached.get("computed_epoch") or 0)) < TTL_SECONDS
            if fresh and cached.get("candidates") is not None:
                cached["cache"] = "HIT"
                return cached
        except Exception:
            pass

    result = _compute(top_n)
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(result))
    except Exception:
        pass
    result["cache"] = "MISS_COMPUTED"
    return result
