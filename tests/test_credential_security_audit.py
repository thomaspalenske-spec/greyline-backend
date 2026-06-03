from pathlib import Path
import subprocess


def run_command(command):
    return subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True
    )


def test_env_file_exists_and_is_ignored():
    env_path = Path(".env")

    assert env_path.exists(), ".env file does not exist"

    ignore_check = run_command("git check-ignore -v .env")
    assert ignore_check.returncode == 0, ".env is not ignored by Git"


def test_env_file_is_not_tracked():
    tracked_check = run_command("git ls-files .env")

    assert tracked_check.stdout.strip() == "", ".env is tracked by Git"


def test_env_file_not_in_git_history():
    history_check = run_command("git log --all -- .env")

    assert history_check.stdout.strip() == "", ".env appears in Git history"


def test_execution_disabled_by_default():
    env_text = Path(".env").read_text()

    assert "AUTONOMOUS_EXECUTION_ENABLED=True" not in env_text
    assert "LIVE_TRADING_ENABLED=True" not in env_text
