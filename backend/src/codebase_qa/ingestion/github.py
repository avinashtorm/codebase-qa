import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

GITHUB_REPO_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<name>[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$"
)


class InvalidRepoUrl(ValueError):
    pass


class RepoTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class GitHubRepo:
    owner: str
    name: str

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"

    @property
    def repo_id(self) -> str:
        return f"{self.owner}__{self.name}".lower()


def parse_github_url(url: str) -> GitHubRepo:
    match = GITHUB_REPO_URL.match(url.strip())
    if match is None or match["name"] in {".", ".."}:
        raise InvalidRepoUrl("only https://github.com/<owner>/<repo> URLs are accepted")
    return GitHubRepo(owner=match["owner"], name=match["name"])


BRANCH_NAME = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<![/.])$")


@dataclass(frozen=True)
class RepoInfo:
    size_kb: int | None = None
    private: bool = False
    default_branch: str = ""
    verified: bool = False


def not_found(repo: GitHubRepo) -> InvalidRepoUrl:
    return InvalidRepoUrl(f"repository {repo.owner}/{repo.name} was not found, or it is private and needs a token")


def fetch_repo_info(repo: GitHubRepo, client: httpx.Client) -> RepoInfo:
    try:
        response = client.get(f"https://api.github.com/repos/{repo.owner}/{repo.name}", timeout=10.0)
    except httpx.HTTPError:
        return RepoInfo()
    if response.status_code == 404:
        raise not_found(repo)
    if response.status_code != 200:
        return RepoInfo()
    data = response.json()
    size = data.get("size")
    return RepoInfo(
        size_kb=int(size) if isinstance(size, int) else None,
        private=bool(data.get("private", False)),
        default_branch=str(data.get("default_branch") or ""),
        verified=True,
    )


def remote_size_kb(repo: GitHubRepo, client: httpx.Client) -> int | None:
    return fetch_repo_info(repo, client).size_kb


def check_size(info: RepoInfo, max_size_mb: int) -> None:
    if info.size_kb is not None and info.size_kb > max_size_mb * 1024:
        raise RepoTooLarge(f"repository is {info.size_kb // 1024} MB, the limit is {max_size_mb} MB")


def check_remote_size(repo: GitHubRepo, max_size_mb: int, client: httpx.Client) -> RepoInfo:
    info = fetch_repo_info(repo, client)
    check_size(info, max_size_mb)
    return info


def validate_branch(branch: str) -> str:
    branch = branch.strip()
    if branch and not BRANCH_NAME.match(branch):
        raise InvalidRepoUrl("branch names may contain letters, digits, '.', '_', '-' and '/'")
    return branch


def branch_exists(repo: GitHubRepo, branch: str, client: httpx.Client) -> bool:
    try:
        response = client.get(f"https://api.github.com/repos/{repo.owner}/{repo.name}/branches/{branch}", timeout=10.0)
    except httpx.HTTPError:
        return True
    return response.status_code != 404


def directory_size_bytes(root: Path) -> int:
    total = 0
    for directory, _, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                total += path.stat().st_size
    return total
