"""
git_utils.py — safe, non-interactive git clone helpers.

Design goals:
- Public HTTPS repos clone with zero credentials and zero prompts.
- Private repos use GITHUB_TOKEN when configured (injected into the URL,
  never logged).
- All git operations run with GIT_TERMINAL_PROMPT=0 so git never hangs
  waiting for interactive input in a container.
- If a clone fails due to auth, a clear ValueError is raised with an
  actionable message rather than a raw git stderr blob.
"""

import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from git import GitCommandError, Repo

from app.core.config import get_settings

settings = get_settings()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _non_interactive_env() -> dict[str, str]:
    """
    Return an environment dict that prevents git from ever prompting for
    credentials.  We start from the current process env so that PATH,
    HOME, etc. are inherited, then override the credential-related keys.
    """
    env = os.environ.copy()
    # Disable all interactive prompts — the single most important flag.
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Use a no-op askpass so git never blocks waiting for a password.
    env["GIT_ASKPASS"] = "true"
    env["SSH_ASKPASS"] = "true"
    return env


def _build_clone_url(repo_url: str) -> str:
    """
    Construct the URL that will actually be passed to git clone.

    Rules:
    - Always use HTTPS (we don't support SSH here).
    - If GITHUB_TOKEN is set, embed it as  https://token@github.com/...
      so the clone is authenticated without any interactive prompt.
    - If no token, return the plain URL — public repos work fine without one.
    - Never log the token; callers should log _safe_url() instead.
    """
    token = (settings.GITHUB_TOKEN or "").strip()

    # Normalise: strip trailing slash
    url = repo_url.strip().rstrip("/")
    parsed = urlparse(url)

    # Only inject token for github.com HTTPS URLs
    if token and parsed.scheme in ("http", "https") and "github.com" in (parsed.netloc or ""):
        # Build  https://<token>@github.com/owner/repo[.git]
        netloc_with_token = f"{token}@{parsed.hostname}"
        if parsed.port:
            netloc_with_token += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc_with_token))

    return url


def _safe_url(repo_url: str) -> str:
    """Return a version of the URL safe to log (token redacted)."""
    return re.sub(r"https://[^@]+@", "https://***@", repo_url)


def _classify_clone_error(exc: GitCommandError, repo_url: str) -> str:
    """
    Translate a raw GitCommandError into a concise, user-facing error category
    string.  Never includes tokens or raw git internals.
    """
    stderr = str(exc).lower()

    if any(kw in stderr for kw in (
        "terminal prompts disabled",
        "could not read username",
        "authentication failed",
        "invalid username or password",
        "bad credentials",
        "401",
        "403",
    )):
        return (
            f"Authentication required — the repository at {_safe_url(repo_url)} "
            "is private or requires a token. "
            "Set GITHUB_TOKEN in your .env file to a valid GitHub personal access token "
            "(Settings → Developer settings → Personal access tokens → repo scope)."
        )

    if any(kw in stderr for kw in (
        "repository not found",
        "not found",
        "does not exist",
        "404",
    )):
        return (
            f"Repository not found — {_safe_url(repo_url)} does not exist or is private. "
            "Check the URL and ensure GITHUB_TOKEN is set if the repository is private."
        )

    if "permission denied" in stderr or "access denied" in stderr:
        return (
            f"Permission denied cloning {_safe_url(repo_url)}. "
            "Ensure GITHUB_TOKEN has the 'repo' scope."
        )

    if any(kw in stderr for kw in ("could not resolve", "unable to connect", "network", "timeout")):
        return (
            f"Network error cloning {_safe_url(repo_url)}. "
            "Check your internet connection and that the URL is reachable."
        )

    if "destination path" in stderr and "already exists" in stderr:
        return (
            f"Clone destination already exists and is not empty. "
            "This is a bug — please report it."
        )

    # Fallback: include the raw stderr but strip any token-like strings
    safe_stderr = re.sub(r"https://[^@\s]+@", "https://***@", str(exc))
    return f"Git clone failed: {safe_stderr}"


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def build_repo_local_path(repository_id: str) -> Path:
    base_path = Path(settings.REPO_STORAGE_ROOT)
    base_path.mkdir(parents=True, exist_ok=True)
    return base_path / repository_id


# ---------------------------------------------------------------------------
# Main clone entry point
# ---------------------------------------------------------------------------

def clone_repository(
    repo_url: str,
    repository_id: str,
    branch: str | None = None,
) -> tuple[Path, str]:
    """
    Clone (or re-use) a repository at *repo_url* into a deterministic local
    path derived from *repository_id*.

    Returns (local_path, commit_sha).

    Raises:
        ValueError — with a clear, user-facing message on any clone failure.
    """
    target_path = build_repo_local_path(repository_id)
    clone_url = _build_clone_url(repo_url)
    env = _non_interactive_env()

    # ------------------------------------------------------------------
    # If the directory already exists, try to reuse / repair it.
    # ------------------------------------------------------------------
    if target_path.exists():
        if (target_path / ".git").exists():
            _fetch_ok = False
            try:
                repo = Repo(target_path)
                repo.remotes.origin.fetch("--all", "--prune", env=env)
                _fetch_ok = True
            except Exception:
                pass

            if not _fetch_ok:
                # Corrupted or stale .git — wipe entirely and re-clone.
                shutil.rmtree(target_path, ignore_errors=True)
                target_path.mkdir(parents=True, exist_ok=True)
            else:
                # Fetch succeeded — clean working tree, keep .git.
                for child in target_path.iterdir():
                    if child.name == ".git":
                        continue
                    if child.is_file():
                        child.unlink()
                    else:
                        shutil.rmtree(child, ignore_errors=True)
        else:
            # Directory exists but no .git — wipe it so clone has a clean target.
            shutil.rmtree(target_path, ignore_errors=True)
            target_path.mkdir(parents=True, exist_ok=True)
    else:
        target_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Clone if we still don't have a .git directory.
    # ------------------------------------------------------------------
    repo = None
    if not (target_path / ".git").exists():
        try:
            if branch:
                try:
                    repo = Repo.clone_from(clone_url, target_path, branch=branch, env=env)
                except GitCommandError as e:
                    branch_err = str(e).lower()
                    if "not found" in branch_err or "did not match" in branch_err or "invalid" in branch_err:
                        # Branch doesn't exist — fall back to default branch.
                        try:
                            repo = Repo.clone_from(clone_url, target_path, env=env)
                        except GitCommandError as e2:
                            raise ValueError(_classify_clone_error(e2, repo_url)) from e2
                    else:
                        raise ValueError(_classify_clone_error(e, repo_url)) from e
            else:
                try:
                    repo = Repo.clone_from(clone_url, target_path, env=env)
                except GitCommandError as e:
                    raise ValueError(_classify_clone_error(e, repo_url)) from e

        except ValueError:
            # Clean up partial clone so next retry starts fresh.
            shutil.rmtree(target_path, ignore_errors=True)
            raise

    else:
        # .git already present — open and try a fetch (best-effort).
        repo = Repo(target_path)
        try:
            repo.remotes.origin.fetch(env=env)
        except GitCommandError:
            pass  # Ignore fetch errors when we already have local data.

    # ------------------------------------------------------------------
    # Checkout the requested branch (best-effort).
    # ------------------------------------------------------------------
    if branch and repo is not None:
        try:
            repo.git.checkout(branch)
        except GitCommandError:
            pass  # Stick with whatever branch was cloned.

    # ------------------------------------------------------------------
    # Resolve HEAD commit.
    # ------------------------------------------------------------------
    try:
        commit_sha = repo.head.commit.hexsha
    except Exception:
        commit_sha = "unknown"

    return target_path, commit_sha
