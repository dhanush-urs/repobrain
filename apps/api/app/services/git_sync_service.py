"""
git_sync_service.py — non-interactive git fetch/pull for already-cloned repos.

Uses the same non-interactive environment as git_utils so that fetch/pull
operations in the worker never hang waiting for credentials.
"""

import os
import subprocess
from pathlib import Path


def _non_interactive_env() -> dict[str, str]:
    """Inherit the process env but disable all interactive git prompts."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"
    env["SSH_ASKPASS"] = "true"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


class GitSyncService:
    def sync_repository(self, local_path: str, branch: str | None = None) -> None:
        repo_path = Path(local_path)

        if not repo_path.exists():
            raise ValueError("Local repository path does not exist")

        if not (repo_path / ".git").exists():
            raise ValueError("Local repository path is not a git repository")

        env = _non_interactive_env()

        self._run_git(["git", "fetch", "--all", "--prune"], repo_path, env=env)

        if branch:
            self._run_git(["git", "checkout", branch], repo_path, env=env, allow_fail=True)
            self._run_git(["git", "pull", "origin", branch], repo_path, env=env, allow_fail=True)
        else:
            self._run_git(["git", "pull"], repo_path, env=env, allow_fail=True)

    def _run_git(
        self,
        cmd: list[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        allow_fail: bool = False,
    ) -> None:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env=env,
        )

        if result.returncode != 0 and not allow_fail:
            raise ValueError(
                f"Git command failed: {' '.join(cmd)} | stderr={result.stderr.strip()}"
            )
