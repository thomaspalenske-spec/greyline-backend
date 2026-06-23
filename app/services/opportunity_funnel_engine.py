from datetime import datetime


class OpportunityFunnelEngine:
    def evaluate(self, candidates):
        rows = candidates or []

        total = len(rows)
        passed_70 = len([r for r in rows if float(r.get("score", 0)) >= 70])
        passed_75 = len([r for r in rows if float(r.get("score", 0)) >= 75])
        passed_80 = len([r for r in rows if float(r.get("score", 0)) >= 80])
        passed_85 = len([r for r in rows if float(r.get("score", 0)) >= 85])

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "symbols_scanned": total,
            "above_70": passed_70,
            "above_75": passed_75,
            "above_80": passed_80,
            "ready_to_execute": passed_85,
            "status": "OPPORTUNITY_FUNNEL_READY",
        }
