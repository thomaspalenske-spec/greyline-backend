from app.services.greyline_system_status_engine import GreyLineSystemStatusEngine


def endpoint(requested_mode="paper"):
    return GreyLineSystemStatusEngine().get_system_status(
        requested_mode=requested_mode
    )
