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


def remote_size_kb(repo: GitHubRepo, client: httpx.Client) -> int | None:
    try:
        response = client.get(f"https://api.github.com/repos/{repo.owner}/{repo.name}", timeout=10.0)
    except httpx.HTTPError:
        return None
    if response.status_code == 404:
        raise InvalidRepoUrl(f"repository {repo.owner}/{repo.name} was not found or is private")
    if response.status_code != 200:
        return None
    size = response.json().get("size")
    return int(size) if isinstance(size, int) else None


def check_remote_size(repo: GitHubRepo, max_size_mb: int, client: httpx.Client) -> None:
    size_kb = remote_size_kb(repo, client)
    if size_kb is not None and size_kb > max_size_mb * 1024:
        raise RepoTooLarge(f"repository is {size_kb // 1024} MB, the limit is {max_size_mb} MB")


def directory_size_bytes(root: Path) -> int:
    total = 0
    for directory, _, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                total += path.stat().st_size
    return total
