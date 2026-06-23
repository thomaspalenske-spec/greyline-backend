from datetime import datetime


class CandidateRejectionSummaryEngine:
    def evaluate(self, queue):
        rows = queue or []

        failed_score = 0
        failed_liquidity = 0
        ready = 0

        for row in rows:
            score = float(row.get("score") or 0)
            liquidity = float(row.get("liquidity_score") or 0)

            if score >= 85 and liquidity >= 70:
                ready += 1
            elif score < 85:
                failed_score += 1
            else:
                failed_liquidity += 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "queue_candidates": len(rows),
            "ready_to_execute": ready,
            "failed_score_threshold": failed_score,
            "failed_liquidity_threshold": failed_liquidity,
            "status": "CANDIDATE_REJECTION_SUMMARY_READY",
        }
