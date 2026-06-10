from app.services.paper_performance_summary_engine import (
    PaperPerformanceSummaryEngine
)


def endpoint():
    return (
        PaperPerformanceSummaryEngine()
        .summarize()
    )
