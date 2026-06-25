from datetime import datetime
from pathlib import Path
import json


class SimulationLedgerEngine:
    _path = Path("app/data/simulation/walk_forward_simulation_ledger.jsonl")

    def record(self, row):
        self._path.parent.mkdir(parents=True, exist_ok=True)

        enriched = {
            "recorded_at": datetime.utcnow().isoformat(),
            **(row or {}),
        }

        with open(self._path, "a") as f:
            f.write(json.dumps(enriched, default=str) + "\n")

        return {
            "recorded": True,
            "path": str(self._path),
            "status": "SIMULATION_LEDGER_RECORDED",
        }

    def load(self, limit=100):
        if not self._path.exists():
            return []

        rows = []
        with open(self._path) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass

        return rows[-limit:]

    def summary(self):
        rows = self.load(limit=10000)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SimulationLedgerEngine",
            "records": len(rows),
            "latest": rows[-1] if rows else None,
            "path": str(self._path),
            "status": "SIMULATION_LEDGER_SUMMARY_READY",
        }

    def clear(self):
        try:
            self._path.unlink(missing_ok=True)
        except TypeError:
            if self._path.exists():
                self._path.unlink()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "engine": "SimulationLedgerEngine",
            "cleared": True,
            "path": str(self._path),
            "status": "SIMULATION_LEDGER_CLEARED",
        }

