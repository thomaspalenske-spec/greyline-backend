from app.services.paper_position_manager_engine import (
    PaperPositionManagerEngine
)


def endpoint():
    return (
        PaperPositionManagerEngine()
        .get_active_positions()
    )
