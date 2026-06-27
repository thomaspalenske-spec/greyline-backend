from datetime import datetime
from pathlib import Path
import subprocess


class SystemHealthSnapshotEngine:
    """
    GreyLine reliability snapshot.

    Purpose:
    - Summarize operational health in one object.
    - Detect stale/missing artifacts.
    - Provide dashboard/API friendly health color.
    - No trading decisions are made here.
    """

    def evaluate(self):
        checks = []

        checks.append(self._check_repo())
        checks.append(self._check_research_artifacts())
        checks.append(self._check_data_directories())

        red = [c for c in checks if c.get("status") == "RED"]
        yellow = [c for c in checks if c.get("status") == "YELLOW"]

        if red:
            overall = "RED"
            summary = "ACTION_REQUIRED"
        elif yellow:
            overall = "YELLOW"
            summary = "DEGRADED_BUT_RUNNING"
        else:
            overall = "GREEN"
            summary = "SYSTEM_HEALTHY"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system": "GreyLine",
            "health_engine": "SYSTEM_HEALTH_SNAPSHOT",
            "overall_health": overall,
            "summary": summary,
            "checks": checks,
            "red_count": len(red),
            "yellow_count": len(yellow),
            "green_count": len([c for c in checks if c.get("status") == "GREEN"]),
            "status": "SYSTEM_HEALTH_SNAPSHOT_READY",
        }

    def _check_repo(self):
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [x for x in result.stdout.splitlines() if x.strip()]
            untracked_research_only = lines and all(x.strip().startswith("?? app/data/research/") for x in lines)

            if not lines:
                status = "GREEN"
                message = "working tree clean"
            elif untracked_research_only:
                status = "YELLOW"
                message = "only generated research artifacts are untracked"
            else:
                status = "YELLOW"
                message = "uncommitted repository changes detected"

            return {
                "check": "git_working_tree",
                "status": status,
                "message": message,
                "details": lines[:20],
            }
        except Exception as e:
            return {
                "check": "git_working_tree",
                "status": "YELLOW",
                "message": "git status unavailable",
                "error": str(e),
            }

    def _check_research_artifacts(self):
        p = Path("app/data/research")
        if not p.exists():
            return {
                "check": "research_artifacts",
                "status": "GREEN",
                "message": "research artifact directory not present",
                "file_count": 0,
            }

        files = [x for x in p.rglob("*") if x.is_file()]
        status = "YELLOW" if files else "GREEN"

        return {
            "check": "research_artifacts",
            "status": status,
            "message": "generated research artifacts present" if files else "no generated research artifacts",
            "file_count": len(files),
            "sample_files": [str(x) for x in files[:10]],
        }

    def _check_data_directories(self):
        required = [
            "app/data",
            "app/services",
            "app/routes",
        ]

        missing = [x for x in required if not Path(x).exists()]

        return {
            "check": "required_directories",
            "status": "RED" if missing else "GREEN",
            "message": "missing required directories" if missing else "required directories present",
            "missing": missing,
        }
