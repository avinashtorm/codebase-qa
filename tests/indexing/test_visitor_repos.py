from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codebase_qa.container import Container
from codebase_qa.indexing.access import AccessStore, is_valid_visitor
from codebase_qa.indexing.janitor import RepoJanitor
from tests.conftest import commit_all, git, write_files
from tests.fakes import VISITOR_A, VISITOR_B, fake_embedder, fake_generator, make_settings

RepoFactory = Callable[..., Path]
START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def make_origin(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    write_files(repo, {f"{name}.py": f"def {name}() -> str:\n    return '{name}'\n"})
    commit_all(repo, "initial")
    return repo


def setup(tmp_path: Path, max_repos: int = 15) -> tuple[Container, AccessStore, RepoJanitor, Clock]:
    clock = Clock()
    container = Container(
        make_settings(tmp_path / "data"), embedder_factory=fake_embedder, generator_factory=fake_generator
    )
    access = AccessStore(container.settings.access_path, clock=clock)
    janitor = RepoJanitor(
        registry=container.registry,
        store=container.store,
        access=access,
        repos_dir=container.settings.repos_dir,
        bm25_dir=container.settings.bm25_dir,
        ttl=timedelta(hours=24),
        max_repos=max_repos,
        clock=clock,
    )
    return container, access, janitor, clock


def index(container: Container, access: AccessStore, tmp_path: Path, name: str, visitor: str = VISITOR_A) -> str:
    record = container.indexer.index(make_origin(tmp_path / "origins", name).as_uri())
    access.grant(record.repo_id, visitor)
    return record.repo_id


def test_visitor_ids_must_be_32_hex_characters() -> None:
    assert is_valid_visitor("0123456789abcdef0123456789abcdef")
    assert not is_valid_visitor("short")
    assert not is_valid_visitor(None)
    assert not is_valid_visitor("Z" * 32)


def test_access_store_tracks_owners_and_pinned_repos(tmp_path: Path) -> None:
    access = AccessStore(tmp_path / "access.json")
    access.grant("mine", VISITOR_A)
    access.pin("demo")
    assert access.visible(VISITOR_A) == {"mine", "demo"}
    assert access.visible(VISITOR_B) == {"demo"}
    assert access.visible(None) == {"demo"}
    access.grant("mine", VISITOR_B)
    assert access.can_see("mine", VISITOR_B)
    access.remove("mine")
    assert not access.can_see("mine", VISITOR_A)


def test_repos_unused_for_24_hours_are_deleted_completely(tmp_path: Path) -> None:
    container, access, janitor, clock = setup(tmp_path)
    old = index(container, access, tmp_path, "old")
    clock.now = START + timedelta(hours=20)
    fresh = index(container, access, tmp_path, "fresh")
    record = next(r for r in container.registry.list() if r.repo_id == old)
    clock.now = START + timedelta(hours=25)

    assert janitor.cleanup() == [old]

    assert [r.repo_id for r in container.registry.list()] == [fresh]
    assert record.collection not in container.store.list_collections()
    assert not (container.settings.bm25_dir / record.collection).exists()
    assert not (container.settings.repos_dir / old).exists()
    assert access.visible(VISITOR_A) == {fresh}


def test_using_a_repo_keeps_it_alive(tmp_path: Path) -> None:
    container, access, janitor, clock = setup(tmp_path)
    repo_id = index(container, access, tmp_path, "used")
    clock.now = START + timedelta(hours=23)
    access.touch(repo_id)
    clock.now = START + timedelta(hours=30)
    assert janitor.cleanup() == []


def test_oldest_repos_are_evicted_beyond_the_cap_and_pinned_repos_stay(tmp_path: Path) -> None:
    container, access, janitor, clock = setup(tmp_path, max_repos=2)
    demo = index(container, access, tmp_path, "demo")
    access.pin(demo)
    ids = []
    for hour, name in enumerate(["first", "second", "third"], start=1):
        clock.now = START + timedelta(hours=hour)
        ids.append(index(container, access, tmp_path, name))
    assert janitor.cleanup() == [ids[0]]
    assert janitor.cleanup(reserve=1) == [ids[1]]
    assert {r.repo_id for r in container.registry.list()} == {demo, ids[2]}


def test_repos_with_running_jobs_are_never_removed(tmp_path: Path) -> None:
    container, access, janitor, clock = setup(tmp_path)
    busy = index(container, access, tmp_path, "busy")
    clock.now = START + timedelta(days=3)
    assert janitor.cleanup(keep={busy}) == []


def test_repos_without_an_owner_entry_expire_by_index_time(tmp_path: Path) -> None:
    container, access, janitor, clock = setup(tmp_path)
    record = container.indexer.index(make_origin(tmp_path / "origins", "orphan").as_uri())
    clock.now = datetime.fromisoformat(record.indexed_at) + timedelta(hours=25)
    assert janitor.cleanup() == [record.repo_id]
