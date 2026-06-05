from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def home():
    return {
        "system": "GreyLine",
        "status": "ONLINE"
    }


@router.get("/readiness")
def readiness():
    return {
        "system": "GreyLine",
        "status": "ONLINE",
        "broker_layer": "INSTALLED",
        "sandbox_readiness_engine": "AVAILABLE",
        "credential_validation_engine": "AVAILABLE",
        "version": "0.0.1"
    }
