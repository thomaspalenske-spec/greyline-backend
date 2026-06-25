from fastapi import APIRouter

from app.services.simulation.historical_csv_import_engine import HistoricalCsvImportEngine

router = APIRouter()


@router.post("/historical-data/import-csv")
def import_historical_csv(symbol: str, input_path: str):
    return HistoricalCsvImportEngine().import_csv(
        symbol=symbol,
        input_path=input_path,
    )
