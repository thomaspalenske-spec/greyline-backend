import json
from pathlib import Path
from app.routes.walk_forward_simulation import walk_forward_simulation_run_clean

class FrozenBacktestRunner:
    def run_manifest(self, manifest_path: str):
        manifest = json.loads(Path(manifest_path).read_text())

        result = walk_forward_simulation_run_clean(
            # calendar-driven execution enforced externally

            symbol=manifest["symbol"],
            start_date=manifest["start_date"],
            end_date=manifest["end_date"],
            step_days=manifest["step_days"],
            starting_capital=manifest["starting_capital"],
        )

        output_path = Path("app/data/simulation_runs/results_baseline_1998.json")
        output_path.write_text(json.dumps({
            "manifest": manifest,
            "result": result
        }, indent=2, default=str))

        return {
            "status": "FROZEN_BACKTEST_COMPLETE",
            "output_path": str(output_path),
            "ending_capital": result["run_result"]["ending_capital"],
            "decision_count": result["run_result"]["decision_count"]
        }
