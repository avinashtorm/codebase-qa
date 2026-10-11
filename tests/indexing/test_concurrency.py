import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codebase_qa.indexing.access import AccessStore
from codebase_qa.jsonfile import JsonFile
from tests.fakes import VISITOR_A, VISITOR_B


def test_concurrent_grants_touches_and_reads_do_not_fail(tmp_path: Path) -> None:
    store = AccessStore(tmp_path / "access.json", touch_interval=timedelta(0))
    errors: list[BaseException] = []

    def worker(number: int) -> None:
        try:
            for step in range(40):
                store.grant(f"repo{number % 3}", VISITOR_A if step % 2 else VISITOR_B)
                store.touch(f"repo{number % 3}")
                store.can_see(f"repo{number % 3}", VISITOR_A)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(number,)) for number in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert store.visible(VISITOR_A) == {"repo0", "repo1", "repo2"}
    assert not list(tmp_path.glob("*.tmp"))


def test_touch_writes_at_most_once_per_interval(tmp_path: Path) -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    store = AccessStore(tmp_path / "access.json", clock=lambda: now[0], touch_interval=timedelta(seconds=60))
    store.grant("repo", VISITOR_A)
    stamp = store.load()["repo"].last_used_at
    now[0] += timedelta(seconds=30)
    store.touch("repo")
    assert store.load()["repo"].last_used_at == stamp
    now[0] += timedelta(seconds=31)
    store.touch("repo")
    assert store.load()["repo"].last_used_at != stamp


def test_json_file_sees_external_changes(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    first, second = JsonFile(path), JsonFile(path)
    first.write({"a": 1})
    assert second.read() == {"a": 1}
    second.write({"a": 2, "b": [1, 2]})
    assert first.read() == {"a": 2, "b": [1, 2]}
