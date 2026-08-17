import json
from datetime import datetime
from pathlib import Path

from app.services.tradestation_quote_live_engine import TradeStationQuoteLiveEngine
from app.services.regime_scoring_engine import RegimeScoringEngine
from app.services.risk_state_scoring_engine import RiskStateScoringEngine
from app.services.breadth_scoring_engine import BreadthScoringEngine
from app.services.setup_scoring_engine import SetupScoringEngine
from app.services.asymmetry_scoring_engine import AsymmetryScoringEngine
from app.services.volatility_scoring_engine import VolatilityScoringEngine


class OpportunityOutcomeTrackerEngine:
    def __init__(self):
        self.data_dir = Path("app/data/opportunity_memory")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_file = self.data_dir / "opportunity_outcome_ledger.jsonl"

    def _last_price(self, symbol):
        quote_result = TradeStationQuoteLiveEngine().get_quote(symbol)
        quotes = (quote_result.get("response_json") or {}).get("Quotes") or []
        row = quotes[0] if quotes else {}

        # None, not 0.0. Three failure paths — no response_json, empty Quotes, unparseable
        # Last — all returned 0.0, which was then written to the DURABLE ledger as
        # snapshot_price with no error marker, indistinguishable from a price. Those rows
        # are permanent, counted as successful records, and later surface as "malformed"
        # buried inside a PENDING bucket that reads as mere immaturity.
        try:
            price = float(row.get("Last") or 0)
        except Exception:
            return None
        return price if price > 0 else None


    def _score_context(self, symbol):
        symbol = (symbol or "").upper().strip()

        try:
            regime = RegimeScoringEngine().score_symbol(symbol)
        except Exception:
            regime = {}

        try:
            risk = RiskStateScoringEngine().score_symbol(symbol)
        except Exception:
            risk = {}

        try:
            breadth = BreadthScoringEngine().score_symbol(symbol)
        except Exception:
            breadth = {}

        try:
            setup = SetupScoringEngine().score_symbol(symbol)
        except Exception:
            setup = {}

        try:
            asymmetry = AsymmetryScoringEngine().score_symbol(symbol)
        except Exception:
            asymmetry = {}

        try:
            volatility = VolatilityScoringEngine().score_symbol(symbol)
        except Exception:
            volatility = {}

        return {
            "regime_score": regime.get("regime_score"),
            "regime": regime.get("regime"),
            "risk_state_score": risk.get("risk_state_score"),
            "risk_state": risk.get("risk_state"),
            "breadth_score": breadth.get("breadth_score"),
            "breadth_state": breadth.get("breadth_state"),
            "setup_score_context": setup.get("setup_score"),
            "setup_state": setup.get("setup_state"),
            "asymmetry_score": asymmetry.get("asymmetry_score"),
            "asymmetry_state": asymmetry.get("asymmetry_state"),
            "volatility_score": volatility.get("volatility_score"),
            "volatility_state": volatility.get("volatility_state"),
        }

    def record(self, candidates):
        rows = []

        for item in candidates or []:
            context = self._score_context(item.get("symbol"))
            row = {
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": item.get("symbol"),
                "option_type": item.get("option_type"),
                "result": item.get("result"),
                "score": item.get("score"),
                "liquidity_score": item.get("liquidity_score"),
                "score_distance_to_execute": item.get("score_distance_to_execute"),
                "directional_bias": item.get("directional_bias"),
                "rank": item.get("rank"),
                "snapshot_price": self._last_price(item.get("symbol")),
                "outcome_status": "PENDING_FORWARD_OUTCOME"
            }
            row.update(context)
            rows.append(row)

        if rows:
            with self.ledger_file.open("a") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")

        return {
            "records_written": len(rows),
            "status": "OPPORTUNITY_OUTCOME_TRACKER_RECORDED"
        }
