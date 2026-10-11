import base64
import json
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.api.repos import resolve_repo
from codebase_qa.container import Container
from codebase_qa.indexing.registry import RepoRecord
from codebase_qa.ingestion import git as git_module
from codebase_qa.ingestion.github import InvalidRepoUrl, validate_branch
from tests.conftest import commit_all, git, write_files
from tests.fakes import VISITOR_A, VISITOR_B, FakeLLM, fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]
TOKEN = "ghp_SECRETTOKEN0000000000000000000000000"


def container_for(tmp_path: Path, api: Callable[[httpx.Request], httpx.Response] | None = None) -> Container:
    container = Container(
        make_settings(tmp_path / "data"),
        embedder_factory=fake_embedder,
        generator_factory=fake_generator,
        llm_factory=lambda _: FakeLLM(),
    )
    if api is not None:
        container.github_transport = httpx.MockTransport(api)
    return container


def github_api(private: bool, branches: tuple[str, ...] = ("main",)) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        authorized = request.headers.get("authorization") == f"Bearer {TOKEN}"
        if private and not authorized:
            return httpx.Response(404, json={"message": "Not Found"})
        if "/branches/" in request.url.path:
            name = request.url.path.split("/branches/", 1)[1]
            return httpx.Response(200 if name in branches else 404, json={})
        return httpx.Response(200, json={"size": 10, "private": private, "default_branch": "main"})

    return handler


def test_clone_passes_the_token_only_through_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append((args, dict(kwargs["env"])))
        return subprocess.CompletedProcess(args, 1, "", f"fatal: auth failed for {TOKEN}")

    monkeypatch.setattr(git_module.subprocess, "run", fake_run)
    with pytest.raises(git_module.GitError) as error:
        git_module.clone_repo("https://github.com/o/r", tmp_path, "o__r", branch="dev", token=TOKEN)
    args, env = calls[0]
    assert (
        TOKEN not in " ".join(args) and ["--branch", "dev"] == args[args.index("--branch") : args.index("--branch") + 2]
    )
    header = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
    assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {header}"
    assert TOKEN not in str(error.value)


def test_branch_names_are_validated() -> None:
    assert validate_branch(" feature/x-1 ") == "feature/x-1"
    for bad in ("-rf", "a..b", "a//b", "x/", "a b", "$(cmd)"):
        with pytest.raises(InvalidRepoUrl):
            validate_branch(bad)


def test_resolve_private_repo_requires_a_token(tmp_path: Path) -> None:
    container = container_for(tmp_path, github_api(private=True, branches=("main", "dev")))
    with pytest.raises(InvalidRepoUrl, match="needs a token"):
        resolve_repo(container, "https://github.com/o/secret")
    target = resolve_repo(container, "https://github.com/o/secret", "dev", TOKEN)
    assert (target.repo_id, target.branch, target.private, target.proven_by_token) == (
        "o__secret@dev",
        "dev",
        True,
        True,
    )
    assert resolve_repo(container, "https://github.com/o/secret", "main", TOKEN).repo_id == "o__secret"
    with pytest.raises(InvalidRepoUrl, match="branch 'nope' was not found"):
        resolve_repo(container, "https://github.com/o/secret", "nope", TOKEN)


def test_indexed_private_repo_is_not_shared_without_a_token(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = container_for(tmp_path, github_api(private=True))
    record = container.indexer.index(make_repo().as_uri(), repo_id="o__secret", private=True)
    container.registry.save(record.collection, RepoRecord(**{**record.__dict__, "url": "https://github.com/o/secret"}))
    container.access.grant("o__secret", VISITOR_A)
    with TestClient(create_app(container)) as client:
        denied = client.post("/repos", json={"url": "https://github.com/o/secret"}, headers={"X-Visitor-Id": VISITOR_B})
        granted = client.post(
            "/repos",
            json={"url": "https://github.com/o/secret", "github_token": TOKEN},
            headers={"X-Visitor-Id": VISITOR_B},
        )
    assert denied.status_code == 400 and "needs a token" in denied.json()["detail"]
    assert granted.status_code == 202 and granted.json()["status"] == "succeeded"
    assert container.access.can_see("o__secret", VISITOR_B)


def test_token_is_never_logged_or_stored(
    tmp_path: Path, make_repo: RepoFactory, caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    container = container_for(tmp_path)
    headers = {"X-Visitor-Id": VISITOR_A}
    with TestClient(create_app(container)) as client:
        good = client.post("/repos", json={"url": make_repo().as_uri(), "github_token": TOKEN}, headers=headers).json()
        good_job = wait_for_job(client, good["job_id"], headers)
        missing = (tmp_path / "missing").as_uri()
        bad = client.post("/repos", json={"url": missing, "github_token": TOKEN}, headers=headers).json()
        bad_job = wait_for_job(client, bad["job_id"], headers)
        repos = client.get("/repos", headers=headers).text
    assert good_job["status"] == "succeeded" and bad_job["status"] == "failed"
    records = [json.dumps(record.__dict__, default=str) for record in caplog.records]
    captured = capfd.readouterr()
    for text in (caplog.text, *records, captured.out, captured.err, json.dumps(good_job), json.dumps(bad_job), repos):
        assert TOKEN not in text
    stored = [path for path in (tmp_path / "data").rglob("*") if path.is_file() and TOKEN.encode() in path.read_bytes()]
    assert stored == []
    assert "git failed" in caplog.text + captured.err


def test_index_a_branch_and_reindex_it(tmp_path: Path, make_repo: RepoFactory) -> None:
    origin = make_repo()
    git(origin, "checkout", "-q", "-b", "feature/x")
    write_files(origin, {"app/feature.py": "def only_on_feature() -> int:\n    return 1\n"})
    commit_all(origin, "feature")
    git(origin, "checkout", "-q", "main")
    container = container_for(tmp_path)
    headers = {"X-Visitor-Id": VISITOR_A}
    with TestClient(create_app(container)) as client:
        job = client.post("/repos", json={"url": origin.as_uri(), "branch": "feature/x"}, headers=headers).json()
        result = wait_for_job(client, job["job_id"], headers)["result"]
        main = wait_for_job(
            client, client.post("/repos", json={"url": origin.as_uri()}, headers=headers).json()["job_id"], headers
        )
    assert result["repo_id"] == "origin@feature-x" and result["branch"] == "feature/x"
    assert "app/feature.py" in container.repo_record("origin@feature-x").files
    assert "app/feature.py" not in container.repo_record("origin").files and main["result"]["branch"] == ""
    git(origin, "checkout", "-q", "feature/x")
    write_files(origin, {"app/feature.py": "def only_on_feature() -> int:\n    return 2\n"})
    commit_all(origin, "feature 2")
    updated, report = container.indexer.reindex(container.repo_record("origin@feature-x"))
    assert report.files_modified == 1 and updated.branch == "feature/x"
