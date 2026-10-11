import base64
import logging
import os
import re
import subprocess
from pathlib import Path

from codebase_qa.fs import remove_tree
from codebase_qa.ingestion.github import InvalidRepoUrl, parse_github_url
from codebase_qa.models import ClonedRepo

logger = logging.getLogger(__name__)

class GitError(RuntimeError):
    pass


def repo_id_from_url(url: str) -> str:
    try:
        return parse_github_url(url).repo_id
    except InvalidRepoUrl:
        pass
    name = url.rstrip("/").split("/")[-1].removesuffix(".git")
    return re.sub(r"[^a-z0-9_.-]", "-", name.lower())


def git_command_name(args: list[str]) -> str:
    return next((arg for arg in args if not arg.startswith("-") and "=" not in arg), "command")


def auth_env(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def run_git(args: list[str], cwd: Path | None = None, timeout: float = 120.0, token: str | None = None) -> str:
    command = git_command_name(args)
    secrets = [token, auth_env(token).get("GIT_CONFIG_VALUE_0", "")] if token else []
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", **auth_env(token)},
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {command} timed out after {timeout:.0f}s") from exc
    if result.returncode != 0:
        stderr = redact(result.stderr.strip()[:2000], [secret for secret in secrets if secret])
        logger.warning("git failed", extra={"command": command, "stderr": stderr})
        raise GitError(f"git {command} failed (the repository may not exist, be private or be unreachable)")
    return result.stdout


def head_sha(repo_path: Path) -> str:
    return run_git(["rev-parse", "HEAD"], cwd=repo_path).strip()


def is_git_checkout(path: Path) -> bool:
    return (path / ".git").exists()


def clone_repo(
    url: str,
    repos_dir: Path,
    repo_id: str | None = None,
    timeout: float = 120.0,
    branch: str = "",
    token: str | None = None,
) -> ClonedRepo:
    resolved_id = repo_id or repo_id_from_url(url)
    target = repos_dir / resolved_id
    if not is_git_checkout(target):
        if target.exists():
            remove_tree(target)
        repos_dir.mkdir(parents=True, exist_ok=True)
        run_git(
            [
                "-c", "core.symlinks=false",
                "-c", "core.hooksPath=/dev/null",
                "-c", "protocol.ext.allow=never",
                "clone", "--depth", "1", "--single-branch", "--no-tags",
                *(["--branch", branch] if branch else []),
                "--", url, str(target),
            ],
            timeout=timeout,
            token=token,
        )
    return ClonedRepo(repo_id=resolved_id, url=url, local_path=str(target), commit_sha=head_sha(target))


def pull_latest(repo_path: Path, timeout: float = 120.0, branch: str = "", token: str | None = None) -> str:
    run_git(["fetch", "--depth", "1", "origin", branch or "HEAD"], cwd=repo_path, timeout=timeout, token=token)
    run_git(["reset", "--hard", "FETCH_HEAD"], cwd=repo_path, timeout=timeout)
    return head_sha(repo_path)


def diff_name_status(repo_path: Path, old_sha: str, new_sha: str) -> list[list[str]]:
    output = run_git(
        ["-c", "core.quotepath=false", "diff", "--name-status", "-M", "--no-color", old_sha, new_sha], cwd=repo_path
    )
    return [line.split("\t") for line in output.splitlines() if line.strip()]
