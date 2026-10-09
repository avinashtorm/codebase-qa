import os
import re
import shutil
import subprocess
from pathlib import Path

from codebase_qa.models import ClonedRepo

GITHUB_URL_PATTERN = re.compile(r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$")


class GitError(RuntimeError):
    pass


def repo_id_from_url(url: str) -> str:
    match = GITHUB_URL_PATTERN.match(url.strip())
    if match:
        return f"{match['owner']}__{match['repo']}".lower()
    name = url.rstrip("/").split("/")[-1].removesuffix(".git")
    return re.sub(r"[^a-z0-9_.-]", "-", name.lower())


def run_git(args: list[str], cwd: Path | None = None, timeout: float = 120.0) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from exc
    if result.returncode != 0:
        raise GitError(f"git {args[0]} failed: {result.stderr.strip()[:500]}")
    return result.stdout


def head_sha(repo_path: Path) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=repo_path).strip()


def is_git_checkout(path: Path) -> bool:
    return (path / ".git").exists()


def clone_repo(url: str, repos_dir: Path, repo_id: str | None = None, timeout: float = 120.0) -> ClonedRepo:
    resolved_id = repo_id or repo_id_from_url(url)
    target = repos_dir / resolved_id
    if not is_git_checkout(target):
        if target.exists():
            shutil.rmtree(target)
        repos_dir.mkdir(parents=True, exist_ok=True)
        run_git(["clone", "--depth", "1", "--single-branch", url, str(target)], timeout=timeout)
    return ClonedRepo(repo_id=resolved_id, url=url, local_path=str(target), commit_sha=head_sha(target))
