from app.services.paper_equity_timeline_engine import PaperEquityTimelineEngine


def endpoint():
    return PaperEquityTimelineEngine().build_timeline()
