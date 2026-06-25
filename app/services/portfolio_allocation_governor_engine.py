from datetime import datetime


class PortfolioAllocationGovernorEngine:
    def evaluate(self, candidates=None, open_positions=None, cash_on_hand=0):
        candidates = candidates or []
        open_positions = open_positions or []

        deployed = []
        held = []

        sector_counts = {}
        for p in open_positions:
            sector = p.get("sector") or p.get("underlying") or p.get("symbol") or "UNKNOWN"
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        for c in candidates:
            symbol = c.get("symbol")
            option_type = c.get("option_type")
            score = float(c.get("adjusted_score") or c.get("score") or 0)
            reliability = float(c.get("signal_reliability_score") or 0)
            liquidity = float(c.get("liquidity_score") or 0)

            allocation_score = round(
                reliability * 0.40 +
                score * 0.30 +
                liquidity * 0.20 +
                (100 if cash_on_hand > 0 else 0) * 0.10,
                2,
            )

            if reliability >= 80 and score >= 85 and liquidity >= 70 and cash_on_hand > 0:
                decision = "DEPLOY"
                deployed.append(symbol)
            elif reliability >= 70:
                decision = "HOLD_FOR_CONFIRMATION"
                held.append(symbol)
            else:
                decision = "SKIP_LOW_RELIABILITY"
                held.append(symbol)

            c["portfolio_allocation_score"] = allocation_score
            c["portfolio_allocation_decision"] = decision

        ranked = sorted(
            candidates,
            key=lambda x: x.get("portfolio_allocation_score", 0),
            reverse=True,
        )

        for i, row in enumerate(ranked, 1):
            row["portfolio_allocation_rank"] = i

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "PortfolioAllocationGovernorEngine",
            "candidates_evaluated": len(ranked),
            "deploy_count": len([r for r in ranked if r.get("portfolio_allocation_decision") == "DEPLOY"]),
            "hold_or_skip_count": len([r for r in ranked if r.get("portfolio_allocation_decision") != "DEPLOY"]),
            "ranked_candidates": ranked,
            "status": "PORTFOLIO_ALLOCATION_GOVERNOR_READY",
        }
