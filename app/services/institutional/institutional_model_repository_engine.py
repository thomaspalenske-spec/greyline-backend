
import json
from datetime import datetime
from pathlib import Path


class InstitutionalModelRepositoryEngine:
    SCHEMA_VERSION = 1

    BASE_PATH = Path(
        "app/data/runtime/"
        "institutional_models"
    )

    def save(
        self,
        symbol,
        model,
    ):
        symbol = str(symbol).upper()

        folder = (
            self.BASE_PATH / symbol
        )
        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            folder / "latest.json"
        )

        payload = {
            "timestamp":
                datetime.utcnow().isoformat(),
            "schema_version":
                self.SCHEMA_VERSION,
            "symbol":
                symbol,
            "model":
                model,
        }

        path.write_text(
            json.dumps(
                payload,
                indent=2,
            )
        )

        return {
            "model_saved": True,
            "path": str(path),
            "status":
                "INSTITUTIONAL_MODEL_SAVED",
        }

    def load(
        self,
        symbol,
    ):
        symbol = str(symbol).upper()

        path = (
            self.BASE_PATH
            / symbol
            / "latest.json"
        )

        if not path.exists():
            return {
                "model_found": False,
                "status":
                    "INSTITUTIONAL_MODEL_NOT_FOUND",
            }

        payload = json.loads(
            path.read_text()
        )

        return {
            "model_found": True,
            "model":
                payload.get("model", {}),
            "timestamp":
                payload.get("timestamp"),
            "status":
                "INSTITUTIONAL_MODEL_READY",
        }
