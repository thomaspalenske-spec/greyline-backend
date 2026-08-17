from datetime import datetime
from pathlib import Path


class EnvironmentFileGuardEngine:

    # .gitignore rules that neutralise a plaintext .env from ever being committed.
    _ENV_IGNORE_RULES = {".env", "*.env", ".env*", "/.env"}

    def evaluate_environment_guard(self):
        # MEASURE the real state rather than asserting it. A hardcoded gitignore_protects_env=True read
        # green even if the rule were ever removed — the exact "assert the safe state" trap. Read the
        # actual files: .env presence and whether .gitignore carries a rule that ignores it.
        env_present = Path(".env").exists()

        gitignore = Path(".gitignore")
        protects = False
        try:
            if gitignore.exists():
                lines = {ln.strip() for ln in gitignore.read_text().splitlines()}
                protects = bool(lines & self._ENV_IGNORE_RULES) or any(
                    ln.endswith("/.env") for ln in lines)
        except Exception:
            protects = False

        approved = protects   # the guard is only "approved" when .env is genuinely ignored
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "env_file_expected": True,
            "env_file_present": env_present,
            # A .env that is NOT ignored would be committable — surface it rather than asserting safety.
            "env_file_tracked_by_git": (env_present and not protects),
            "gitignore_protects_env": protects,
            "credentials_present": env_present,
            "environment_guard_approved": approved,
            "status": "ENVIRONMENT_GUARD_ACTIVE" if approved else "ENVIRONMENT_GUARD_AT_RISK",
        }
