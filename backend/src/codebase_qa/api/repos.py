import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from codebase_qa.api.schemas import RepoOut
from codebase_qa.container import Container
from codebase_qa.indexing.jobs import Job, JobManager, Progress
from codebase_qa.ingestion.git import repo_id_from_url
from codebase_qa.ingestion.github import (
    InvalidRepoUrl,
    branch_exists,
    check_remote_size,
    not_found,
    parse_github_url,
    validate_branch,
)


@dataclass(frozen=True)
class RepoTarget:
    url: str
    repo_id: str
    branch: str = ""
    private: bool = False
    proven_by_token: bool = False


def branch_suffix(branch: str) -> str:
    return f"@{re.sub(r'[^a-z0-9._-]', '-', branch.lower())}" if branch else ""


def github_client(services: Container, token: str | None) -> httpx.Client:
    secret = token or services.settings.github_token
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    return httpx.Client(headers=headers, transport=services.github_transport)


def resolve_repo(services: Container, url: str, branch: str = "", token: str | None = None) -> RepoTarget:
    settings = services.settings
    branch = validate_branch(branch)
    if settings.allow_local_repos and url.startswith("file://"):
        return RepoTarget(url, repo_id_from_url(url) + branch_suffix(branch), branch)
    repo = parse_github_url(url)
    with github_client(services, token) as client:
        info = check_remote_size(repo, settings.max_repo_size_mb, client)
        if info.private and not token:
            raise not_found(repo)
        if branch and branch == info.default_branch:
            branch = ""
        if branch and not branch_exists(repo, branch, client):
            raise InvalidRepoUrl(f"branch '{branch}' was not found in {repo.owner}/{repo.name}")
    proven = bool(token) and info.verified
    return RepoTarget(repo.url, repo.repo_id + branch_suffix(branch), branch, info.private, proven)


def index_action(services: Container, target: RepoTarget, token: str | None) -> Callable[[Progress], dict[str, Any]]:
    secret = [token] if token else []

    def action(progress: Progress) -> dict[str, Any]:
        try:
            record = services.indexer.index(
                target.url,
                repo_id=target.repo_id,
                progress=progress,
                branch=target.branch,
                token=secret[0] if secret else None,
                private=target.private,
            )
        finally:
            secret.clear()
        services.answer_cache.invalidate(record.repo_id)
        return RepoOut.from_record(record).model_dump()

    return action


def submit_index(services: Container, jobs: JobManager, target: RepoTarget, token: str | None = None) -> Job:
    active = jobs.active_for(target.repo_id)
    if active is not None:
        return active
    services.janitor.cleanup(keep=jobs.active_repo_ids() | {target.repo_id}, reserve=1)
    return jobs.submit("index", target.repo_id, index_action(services, target, token))
