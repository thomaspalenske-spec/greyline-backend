from fastapi import FastAPI

app = FastAPI(title="GreyLine Backend Server")


@app.get("/")
def home():
    return {
        "system": "GreyLine",
        "status": "ONLINE"
    }


@app.get("/readiness")
def readiness():
    return {
        "system": "GreyLine",
        "status": "ONLINE",
        "broker_layer": "INSTALLED",
        "sandbox_readiness_engine": "AVAILABLE",
        "credential_validation_engine": "AVAILABLE",
        "version": "0.0.1"
    }


from app.services.paper_trading_command_center_engine import PaperTradingCommandCenterEngine


@app.get("/paper-trading-command-center")
def paper_trading_command_center():
    engine = PaperTradingCommandCenterEngine()
    return engine.get_command_center()
