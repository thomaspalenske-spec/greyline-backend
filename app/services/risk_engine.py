from datetime import datetime
from os import getenv

from app.services.paper_drawdown_engine import PaperDrawdownEngine
from app.services.portfolio_correlation_engine import PortfolioCorrelationEngine
from app.services.portfolio_directional_exposure_engine import PortfolioDirectionalExposureEngine
from app.services.position_exposure_limit_engine import PositionExposureLimitEngine


def _net_bias(net_exposure_pct):
    if net_exposure_pct is None:
        return "UNKNOWN"
    if net_exposure_pct > 5:
        return "BULLISH"
    if net_exposure_pct < -5:
        return "BEARISH"
    return "NEUTRAL"


def entry_allowed(risk_result, candidate_direction):
    """
    Direction-aware entry permission given an evaluated risk result.

    - HALTED / any HARD block (drawdown, correlation, position limits) -> block all.
    - Directional-only block -> block SAME-direction entries; allow opposite/neutral
      entries so the book can rebalance (matches the exposure engine's intent).
    """
    if risk_result.get("risk_state") == "HALTED":
        return False, "Risk state HALTED"

    if risk_result.get("hard_block"):
        return False, "Hard risk block: " + ", ".join(risk_result.get("hard_block_factors", []))

    if risk_result.get("directional_soft_block"):
        net_bias = risk_result.get("net_directional_bias")
        direction = str(candidate_direction or "").upper()
        if direction in ("BULLISH", "BEARISH") and direction == net_bias:
            return False, f"Directional exposure HIGH ({net_bias}); same-direction entries blocked (rebalance only)"
        return True, f"Directional exposure HIGH; opposite/neutral rebalancing entry allowed"

    # Safety fallback: only NORMAL is permitted. Any other non-normal state (e.g. a
    # DEFENSIVE with no recognized flag) blocks rather than silently allowing.
    if risk_result.get("risk_state") != "NORMAL":
        return False, f"Risk state {risk_result.get('risk_state')} does not permit entry"

    return True, "Risk normal"


class RiskEngine:
    """
    Portfolio-level risk gate consumed by GreyLineMasterDecisionEngine.

    Live dimensions: drawdown, correlation (sector clustering), directional exposure,
    and hard numeric position/exposure limits. Liquidity is an honest placeholder.

    HARD blocks (drawdown DEFENSIVE/HALTED, correlation HIGH, limit breach) stop new
    entries in ANY direction. A DIRECTIONAL-only block stops same-direction entries but
    permits opposite/neutral ones to rebalance (see entry_allowed). Any dimension
    compute failure degrades to a visible, non-blocking state — never crashes.
    """

    def __init__(self):
        self.liquidity_state = "STABLE"  # placeholder — not computed from live data yet.

    def evaluate(self):
        halt_pct = float(getenv("GREYLINE_RISK_HALT_DRAWDOWN_PCT", "20"))
        defensive_pct = float(getenv("GREYLINE_RISK_DEFENSIVE_DRAWDOWN_PCT", "10"))

        # --- drawdown ---
        try:
            drawdown = PaperDrawdownEngine().calculate()
            max_drawdown_pct = float(drawdown.get("max_drawdown_pct") or 0)
            peak_equity = drawdown.get("peak_equity")
            if max_drawdown_pct >= halt_pct:
                drawdown_state = "HALTED"
            elif max_drawdown_pct >= defensive_pct:
                drawdown_state = "DEFENSIVE"
            else:
                drawdown_state = "NORMAL"
            drawdown_source = "LIVE_PAPER_EQUITY_DRAWDOWN"
        except Exception:
            max_drawdown_pct, peak_equity = None, None
            drawdown_state = "UNKNOWN"
            drawdown_source = "DEGRADED_COMPUTE_FAILED"

        # --- correlation ---
        try:
            correlation_risk = PortfolioCorrelationEngine().evaluate().get("correlation_risk", "LOW")
            correlation_source = "LIVE_SECTOR_CLUSTER_CORRELATION"
        except Exception:
            correlation_risk = "UNKNOWN"
            correlation_source = "DEGRADED_COMPUTE_FAILED"

        # --- directional exposure ---
        try:
            direc = PortfolioDirectionalExposureEngine().evaluate()
            directional_risk = direc.get("directional_risk", "LOW")
            net_exposure_pct = direc.get("net_exposure_pct")
            directional_source = "LIVE_NET_DIRECTIONAL_EXPOSURE"
        except Exception:
            directional_risk = "UNKNOWN"
            net_exposure_pct = None
            directional_source = "DEGRADED_COMPUTE_FAILED"

        # --- hard position/exposure limits ---
        try:
            limits = PositionExposureLimitEngine().evaluate()
            limit_breaches = limits.get("breaches", [])
            limits_source = "LIVE_POSITION_EXPOSURE_LIMITS"
        except Exception:
            limits = {}
            limit_breaches = []
            limits_source = "DEGRADED_COMPUTE_FAILED"

        # --- resolve ---
        hard_block_factors = []
        if drawdown_state == "HALTED":
            hard_block_factors.append("DRAWDOWN_HALT")
        if drawdown_state == "DEFENSIVE":
            hard_block_factors.append("DRAWDOWN_DEFENSIVE")
        if correlation_risk == "HIGH":
            hard_block_factors.append("CORRELATION_HIGH")
        for b in limit_breaches:
            hard_block_factors.append(f"LIMIT_BREACH::{b}")

        directional_soft_block = directional_risk == "HIGH"
        hard_block = len(hard_block_factors) > 0

        blocking_factors = list(hard_block_factors)
        if directional_soft_block:
            blocking_factors.append("DIRECTIONAL_EXPOSURE_HIGH")

        if drawdown_state == "HALTED":
            risk_state = "HALTED"
        elif blocking_factors:
            risk_state = "DEFENSIVE"
        else:
            risk_state = "NORMAL"

        degraded = "DEGRADED_COMPUTE_FAILED" in (
            drawdown_source, correlation_source, directional_source, limits_source
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "risk_state": risk_state,
            "hard_block": hard_block,
            "hard_block_factors": hard_block_factors,
            "directional_soft_block": directional_soft_block,
            "blocking_factors": blocking_factors,
            "net_directional_bias": _net_bias(net_exposure_pct),
            "drawdown_state": drawdown_state,
            "max_drawdown_pct": round(max_drawdown_pct, 2) if max_drawdown_pct is not None else None,
            "peak_equity": peak_equity,
            "halt_drawdown_pct": halt_pct,
            "defensive_drawdown_pct": defensive_pct,
            "correlation_risk": correlation_risk,
            "directional_risk": directional_risk,
            "net_exposure_pct": net_exposure_pct,
            "liquidity_state": self.liquidity_state,
            "limit_breaches": limit_breaches,
            "position_limits": limits,
            "risk_inputs": {
                "drawdown": drawdown_source,
                "correlation": correlation_source,
                "directional": directional_source,
                "position_limits": limits_source,
                "liquidity": "PLACEHOLDER_NOT_COMPUTED",
            },
            "status": "RISK_STATE_DEGRADED" if degraded else "RISK_STATE_READY",
        }

    def evaluate_risk_state(self):
        # Backward-compatible string accessor (used by GreyLineMasterDecisionEngine).
        return self.evaluate()["risk_state"]
