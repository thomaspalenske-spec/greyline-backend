from datetime import datetime
from pathlib import Path

from app.services.persistence.json_store import append_jsonl


class DecisionShadowLogEngine:
    """
    Shadow-logs, for each decision, BOTH the live momentum-proxy direction AND the
    real-flow-implied direction (institutional buying vs selling) — without changing
    the live decision. This turns a market session into a controlled A/B: after the
    horizon, ShadowComparisonEngine grades each and reports which predicts better (MCC).

    Fail-safe: any error here is swallowed — shadow logging must never affect trading.
    """

    LEDGER = Path("app/data/decision_shadow/decision_shadow_log.jsonl")

    def log(self, symbol, candidate, intelligence):
        try:
            momentum = str((candidate or {}).get("directional_bias") or "").upper()
            b = (intelligence or {}).get("institutional_buying_score")
            s = (intelligence or {}).get("institutional_selling_score")

            if isinstance(b, (int, float)) and isinstance(s, (int, float)) and b != s:
                flow = "BULLISH" if b > s else "BEARISH"
            else:
                flow = "NEUTRAL"  # no directional flow info (equal / defaulted / missing)

            intel = intelligence or {}
            append_jsonl(self.LEDGER, {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "result": (candidate or {}).get("result"),
                "momentum_direction": momentum,
                "flow_direction": flow,
                "buying_score": b,
                "selling_score": s,
                # All real feed scores (0-100, >50 bullish) so per-feed predictive skill
                # can be measured from data after the session — no pre-committed composite.
                "greek_flow_score": intel.get("greek_flow_score"),
                "spot_gamma_score": intel.get("spot_gamma_score"),
                "lit_flow_score": intel.get("lit_flow_score"),
                "dark_pool_score": intel.get("dark_pool_score"),
                "overall_institutional_score": intel.get("overall_institutional_score"),
                "agree": momentum == flow and flow in ("BULLISH", "BEARISH"),
            })
        except Exception:
            pass
