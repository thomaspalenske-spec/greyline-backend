from fastapi import FastAPI
from app.routes.governance import router as governance_router

app = FastAPI(title="GreyLine Backend")

app.include_router(governance_router)


@app.get("/")
def root():
    return {
        "system": "GreyLine",
        "status": "ONLINE"
    }

